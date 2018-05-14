#!/usr/bin/env python

import sys
sys.path.insert(0, '..')  # Give me an access to juice

import logging
import os
from pprint import pprint

import pymysql
import yaml

import juice as j

# G5k parameters
JOB_NAME = 'juice-split-brain'
WALLTIME = '61:59:00'
RESERVATION = None
CLUSTER = 'ecotype'
SITE = 'nantes'

# Experimentation parameters
DATABASES = ['mariadb', 'galera', 'cockroachdb']

CONF = {
  'enable_monitoring': True,
  'g5k': {'dhcp': True,
          'env_name': 'debian9-x64-nfs',
          'job_name': JOB_NAME,
          # 'queue': 'testing',
          'walltime': WALLTIME,
          'reservation': RESERVATION,
          'resources': {'machines': [{'cluster': CLUSTER,
                                      'nodes': 9
                                      'roles': ['chrony',
                                                'database',
                                                'sysbench',
                                                'openstack',
                                                'rally'],
                                      'primary_network': 'n1',
                                      'secondary_networks': ['n2']},
                                     {'cluster': CLUSTER,
                                      'nodes': 1,
                                      'roles': ['registry', 'control'],
                                      'primary_network': 'n1',
                                      'secondary_networks': []}],
                        'networks': [{'id': 'n1',
                                      'roles': ['control_network'],
                                      'site': SITE,
                                      'type': 'prod'},
                                      {'id': 'n2',
                                      'roles': ['database_network'],
                                      'site': SITE,
                                      'type': 'kavlan'},
                                     ]}},
  'registry': {'ceph': True,
               'ceph_id': 'discovery',
               'ceph_keyring': '/home/discovery/.ceph/ceph.client.discovery.keyring',
               'ceph_mon_host': ['ceph0.rennes.grid5000.fr',
                                 'ceph1.rennes.grid5000.fr',
                                 'ceph2.rennes.grid5000.fr'],
               'ceph_rbd': 'discovery_kolla_registry/datas',
               'type': 'internal'},
  'tc': {'constraints': [{'delay': '0ms',
                          'src': 'database',
                          'dst': 'database',
                          'loss': 0,
                          'rate': '10gbit',
                          "network": "database_network"}],
         'default_delay': '0ms',
         'default_rate': '10gbit',
         'enable': True,
         'groups': ['database']}
}

SCENARIOS = [
  "keystone/authenticate-user-and-validate-token.yaml"
  , "keystone/create-add-and-list-user-roles.yaml"
  , "keystone/create-and-list-tenants.yaml"
  , "keystone/get-entities.yaml"
  , "keystone/create-and-update-user.yaml"
  , "keystone/create-user-update-password.yaml"
  , "keystone/create-user-set-enabled-and-delete.yaml"
  , "keystone/create-and-list-users.yaml"
]


logging.basicConfig(level=logging.INFO)

def teardown():
    try:
        j.destroy()
        # TODO: reset iptable DROP
    except Exception as e:
        logging.warning("Setup went wrong with message: %s" % e)


def init():
    j.deploy(conf=CONF, xp_name=JOB_NAME)
    teardown()



def split_brain():
    sweeper = ParamSweeper(
        SWEEPER_DIR,
        sweeps=sweep({
              'db':    DATABASES
        }))

    while sweeper.get_remaining():
        combination = sweeper.get_next()
        logging.info("Treating combination %s" % pformat(combination))

        rdbms = combination['db']

        try:
            # Get the address of the databases
            db_hosts = []
            db_master_host = None
            with open(os.path.join(JOB_NAME, 'env'), "r") as f:
                db_hosts = yaml.load(f)['roles']['database']
                db_master_host = db_hosts[0]
                logging.info("Database Hosts are %s", db_hosts)
                logging.info("Database Master is %s", db_master_host)

            # Let's get it started hun!
            j.deploy(CONF, rdbms, xp_name="split-brain-%s" % rdbms)
            j.openstack(rdbms)
            # TODO: implement drop after `n` iteration with rally hook:
            # - http://docs.xrally.xyz/projects/openstack/en/0.12.0/plugins/implementation/hook_and_trigger_plugins.html
            # - http://docs.xrally.xyz/projects/openstack/en/0.12.0/plugins/plugin_reference.html#event-hook-trigger
            j.rally(SCENARIOS, "keystone", burst=True)
            j.backup()

            # Everything works well, mark combination as done
            sweeper.done(combination)
            logging.info("End of combination %s" % pformat(combination))

        except Exception as e:
            # Oh no, something goes wrong! Mark combination as cancel for
            # a later retry
            logging.error("Combination %s Failed with message %s" % (pformat(combination), e))
            sweeper.cancel(combination)

        finally:
            teardown()


if __name__ == '__main__':
    # Do the initial reservation and boilerplate
    init()

    # Run experiment
    split_brain()
