
import os
import json
import time
import digitalocean
import fabric.api as fab
import fabric
# from fabric.context_managers import lcd

import invoke as inv


FILE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_FILE = os.path.realpath('./do_config.json')


def create_default_config():
    if not os.path.isfile(CONFIG_FILE):
        config = dict(
            key='digital_ocean_key',
            ssh_keyfile='~/.ssh/id_rsa.pub',
            user='root',
            host='',
        )
        with open(CONFIG_FILE, 'w') as f:
            f.write(json.dumps(config, indent=2))

    fab.local('vim {}'.format(CONFIG_FILE))


def get_config():
    class Config(object):
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def to_dict(self):
            return {k: v for (k, v) in self.__dict__.items()}

    if not os.path.isfile(CONFIG_FILE):
        create_default_config()

    with open(CONFIG_FILE) as f:
        config = Config(**json.loads(f.read()))
    return config


def save_config(config_obj):
    with open(CONFIG_FILE, 'w') as f:
        f.write(json.dumps(config_obj.to_dict(), indent=2))


config = get_config()
fab.env.hosts = [config.host]
fab.env.user = config.user
fab.env.key_filename = config.ssh_keyfile


@fab.task
def run_script_task(command_str):
    commands = [s.strip() for s in command_str.split('\n') if s.strip()]
    for cmd in commands:
        fab.run(cmd)


def run_script(command_str):
    fabric.tasks.execute(run_script_task, command_str)


@inv.task
def _config(ctx, force=False):
    """
    Modify config for talking to digital ocean
    """
    create_default_config()


@inv.task
def _update_apt(ctx):
    """
    Update apt-get for droplet
    """
    run_script(
        """
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
        sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
        add-apt-repository -y ppa:jonathonf/vim
        apt-get update
        """
    )


@inv.task(_update_apt)
def _install_vim(ctx):
    """
    Install vim on droplet
    """
    run_script(
        """
        apt-get install -y vim-nox
        """
    )


@inv.task(_update_apt)
def _install_python(ctx):
    """
    Install python on droplet
    """
    run_script(
        """
        apt-get -y install python python-dev
        apt-get -y install python-pip
        """
    )


@inv.task(_install_python, _install_vim)
def _personalize(ctx):
    """
    Personalize droplet
    """
    run_script(
        """
        sudo apt install -y  ntp
        cd ~
        git clone https://github.com/robdmc/dot_files.git
        (cd ~/dot_files/ && python deploy.py)
        """
    )


def get_droplets():
        _config = get_config()
        manager = digitalocean.Manager(token=_config.key)
        return {
            d.id: d for d in manager.get_all_droplets()
        }


@inv.task
def ls_droplets(ctx):
    """
    List all droplets
    """
    for d in sorted(get_droplets().values(), key=lambda dr: dr.name):
        print d.id, d.name, d.ip_address


@inv.task
def ssh(ctx, name=None):
    """
    ssh into droplet
    """
    config = get_config()
    droplets = get_droplets()
    if name is None:
        if len(droplets) != 1:
            raise ValueError('\n\nMore than one droplet.  Specify droplet name')
        _, droplet = droplets.popitem()
    else:
        droplet_candidates = [
            d for d in get_droplets().values() if d.name == name]
        if len(droplet_candidates) == 1:
            droplet = droplet_candidates[0]
        else:
            raise ValueError(
                '\n\nMore than one droplet named {}'.format(name)
            )

    fab.local('ssh {}@{}'.format(config.user, droplet.ip_address))


@inv.task
def destroy_droplet(ctx, droplet_id=''):
    """
    Destroy droplet
    """
    droplet = get_droplets().get(int(droplet_id))
    if droplet is None:
        raise ValueError('\n\nNo droplet with id: {}\n\n'.format(droplet_id))
    droplet.destroy()


def wait_droplet(name):
    config = get_config()
    while True:
        manager = digitalocean.Manager(token=config.key)
        droplets = [d for d in manager.get_all_droplets() if d.name == name]
        if droplets:
            print '{} created now waiting for activation'.format(name)
            droplet = droplets[0]
            if droplet.status == 'active':
                print 'now_active: {}'.format(name)
                break
        time.sleep(1)


@inv.task(
    help=dict(
        name='required droplet name',
        size='default(512mb)',
        dont_store_name='if set, name will not be stored in local config',
    )
)
def create_droplet(
        ctx, name='', size='512mb', region='nyc1', dont_store_name=False):
    """
    Create a new droplet
    """
    if not name:
        raise ValueError('\n\nYou must supply a droplet_name\n\n')
    config = get_config()
    manager = digitalocean.Manager(token=config.key)
    droplet = digitalocean.Droplet(
        token=config.key,
        name=name,
        region=region,
        image='ubuntu-16-04-x64',
        size_slug=size,
        ssh_keys=manager.get_all_sshkeys(),
        backups=False
    )
    droplet.create()
    wait_droplet(name)

    if not dont_store_name:
        droplet = [d for d in get_droplets().values() if d.name == name][0]
        config = get_config()
        config.host = droplet.ip_address
        save_config(config)


@inv.task
def _install_conda(ctx):
    """
    install conda
    """
    run_script(
        """
        wget --quiet https://repo.continuum.io/miniconda/Miniconda3-4.3.14-Linux-x86_64.sh -O ~/miniconda.sh
        /bin/bash ~/miniconda.sh -b
        echo ". /root/miniconda3/bin/activate " >> ~/.bashrc
        . ~/.bashrc
        conda update -y conda
        """
    )


@inv.task(
    _personalize,
    _install_conda,
)
def _initialize_droplet(ctx):
    """
    Initialize an already created droplet
    """


@inv.task(_initialize_droplet)
def _install_python(ctx):
    """
    Install python on droplet
    """
    run_script(
        """
        apt-get -y install python python-dev
        apt-get -y install python-pip
        """
    )


@inv.task(_install_python)
def _install_docker(ctx):
    """
    Install docker on droplet
    """
    run_script(
        """
        sudo apt-get install -y docker-ce
        pip install docker-compose
        """
    )

# @inv.task(_initialize_droplet)
# def _install_project(ctx):
#     """
#     Install the project
#     """
#     run_script(
#         """
#         (rm -rf ~/cointick 2> /dev/null || true)
#         (cd ~ && git clone https://github.com/robdmc/cointick)
#         (/root/miniconda3/bin/conda clean --packages -y)
#         (cd ~/cointick && /root/miniconda3/bin/conda env create --force -q -f environment.yml)
#         """
#     )


@inv.task(_install_docker)
def deploy(ctx):
    """
    Deploy this project
    :return:
    """


# @inv.task
# def pull_data(ctx):
#     """
#     Install the project
#     """
#     config = get_config()
# 
#     run_script(
#         """
#         (cd ~/cointick/ && tar -czvf ~/latest_coin_data.tar.gz ./five_minute_data)
#         """
#     )
#     fab.local('rm -rf five_minute_data/')
#     fab.local('scp root@{}:/root/latest_coin_data.tar.gz .'.format(config.host))
#     fab.local('tar -xvf latest_coin_data.tar.gz')
# 
# 
# @inv.task
# def pull_mining_data(ctx):
#     """
#     Install the project
#     """
#     config = get_config()
# 
#     run_script(
#         """
#         (cd ~/cointick/ && tar -czvf ~/latest_coin_data.tar.gz ./five_minute_data/whattomine*)
#         """
#     )
#     fab.local('rm -rf five_minute_data/')
#     fab.local('scp root@{}:/root/latest_coin_data.tar.gz .'.format(config.host))
#     fab.local('tar -xvf latest_coin_data.tar.gz')
