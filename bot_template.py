#! /usr/bin/env python


# example of how to load into a dataframe
# ddf[ddf.symbol.isin(['BTC', 'ETH'])].compute()

import datetime
import time
import json
import numpy as np
import pandas as pd
import os
import requests
from crontabs import Cron, Tab
import logging
import daiquiri

# make directory if it doesn't exist
OUTPUT_PATH = os.path.join(os.path.realpath(os.path.dirname(__file__)), 'five_minute_data')

daiquiri.setup(level=logging.INFO)

# Will download the top this many coins by rank
MIN_RANK = 120

# URI of the coinmarketcap api
URI = f'https://api.coinmarketcap.com/v1/ticker/?limit={MIN_RANK}'

# URI of whattomine for two 1080ti cards
URI_MINING = 'https://whattomine.com/coins.json?adapt_q_1080Ti=2&adapt_1080Ti=true'

# Turn these fields into float32 fields on the dataframe
NUMERIC_FIELDS = [
    'rank',
    'price_usd',
    'price_btc',
    '24h_volume_usd',
    'market_cap_usd',
    'available_supply',
    'total_supply',
    'max_supply',
    'last_updated',
]

# Turn these fields into strings
STR_FIELDS = [
    'id',
    'symbol',
]


def download(uri):
    # will retry the api this many times before erroring
    num_retries = 5
    for nr in range(num_retries):
        result = requests.get(uri)

        # if successful api download
        if result.status_code == 200:
            result = requests.get(URI)

            # create a timestamp to identify download time
            now = datetime.datetime.utcnow()

            # create a dataframe and make the fields have the proper type
            df = pd.DataFrame(result.json())
            for field in NUMERIC_FIELDS:
                df.loc[:, field] = df.loc[:, field].astype(np.float32)
            for field in STR_FIELDS:
                df.loc[:, field] = [str(s) for s in df.loc[:, field]]

            # add extra convenience fields to the dataframe
            df.loc[:, 'last_downloaded'] = now
            df = df[STR_FIELDS + ['last_downloaded'] + NUMERIC_FIELDS]
            df.loc[:, 'last_updated'] = [datetime.datetime.fromtimestamp(int(t)) for t in df.last_updated]
            return df
        else:
            time.sleep(2)

    raise RuntimeError(f'Price download failed.  Max retries failed at time {now}')


def download_mining(uri):
    # will retry the api this many times before erroring
    num_retries = 5
    for nr in range(num_retries):
        res = requests.get(uri)

        # create a timestamp to identify download time
        now = datetime.datetime.utcnow()

        # if successful api download
        if res.status_code == 200:
            # parse the result into json
            doc = json.loads(res.text)['coins']

            # populate a dataframe
            rec_list = []
            for coin, rec in doc.items():
                rec.update(coin=coin)
                rec_list.append(rec)

            fields = [
                'coin', 'algorithm',
                'nethash', 'difficulty', 'block_time', 'block_reward',
                'exchange_rate', 'btc_revenue',
            ]
            float_fields = fields[2:]

            df = pd.DataFrame(rec_list)[fields]
            df.insert(0, 'last_downloaded', now)
            for field in float_fields:
                df.loc[:, field] = [float(x) for x in df.loc[:, field]]
            df.rename(columns={'exchange_rate': 'btc_price'}, inplace=True)
            return df
        else:
            time.sleep(2)

    raise RuntimeError(f'Mining download failed.  Max retries failed at time {now}')


def save_csv(df, file_name):
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    append = os.path.isfile(file_name)
    needs_header = not append
    df.to_csv(file_name, mode='a', header=needs_header, index=False)


def snapshot():
    logger = daiquiri.getLogger('snapshot')
    df = download(URI)

    t = df.last_downloaded.iloc[0]
    base_name = f'five-minute-{t.year:04d}-{t.month:02d}.csv'
    file_name = os.path.join(OUTPUT_PATH, base_name)
    save_csv(df, file_name)
    logger.info(f'downloaded {len(df)} records: {datetime.datetime.utcnow()}')

    # inform dead man's snitch
    requests.get('https://nosnch.in/5af459f46b')  # sfo
    # requests.get('https://nosnch.in/8915aa097b')  # nyc


def mining_snapshot():
    logger = daiquiri.getLogger('snapshot_what_to_mine')

    btc_price = download(URI).set_index('symbol').loc['BTC', 'price_usd']
    df = download_mining(URI_MINING)
    df.loc[:, 'usd_revenue'] = btc_price * df.btc_revenue
    df.sort_values(by='usd_revenue', inplace=True, ascending=False)
    t = df.last_downloaded.iloc[0]
    base_name = f'whattomine-{t.year:04d}-{t.month:02d}.csv'
    file_name = os.path.join(OUTPUT_PATH, base_name)
    save_csv(df, file_name)
    logger.info(f'downloaded {len(df)} whattomine records: {datetime.datetime.utcnow()}')

    # inform dead man's snitch
    requests.get('https://nosnch.in/f48cfdd3d3')  # sfo
    # requests.get('https://nosnch.in/08a8b1e1ea')  # nyc


Cron().schedule(
    Tab('coin_market_cap', verbose=False).every(minutes=5).run(snapshot),
    Tab('whattomine', verbose=False).every(minutes=10).run(mining_snapshot),

).go()
