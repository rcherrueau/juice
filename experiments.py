#!/usr/bin/env python

import logging
import copy
from pprint import pformat

import juice as j
from execo_engine.sweep import (ParamSweeper, sweep)


WALLTIME = '04:58:00'
# WALLTIME = '01:40:00'
RESERVATION = '2018-03-21 04:01:01'
# RESERVATION = None

# DATABASES = ['mariadb', 'cockroachdb']
DATABASES = ['mariadb']
CLUSTER_SIZES = [3, 25, 45]
# CLUSTER_SIZES = [2]
DELAYS = [0, 50, 150]
# DELAYS = [0]

MAX_CLUSTER_SIZE = max(CLUSTER_SIZES)

CONF = {
  'enable_monitoring': False,
  'g5k': {'dhcp': True,
          'env_name': 'debian9-x64-nfs',
          'job_name': 'juice-tests',
          'walltime': WALLTIME,
          'reservation': RESERVATION,
          'resources': {'machines': [{'cluster': 'graphene',
                                      'nodes': MAX_CLUSTER_SIZE,
                                      'roles': ['chrony',
                                                'database',
                                                'sysbench',
                                                'openstack',
                                                'rally'],
                                      'primary_network': 'n1',
                                      'secondary_networks': []},
                                     {'cluster': 'graphene',
                                      'nodes': 1,
                                      'roles': ['registry', 'control'],
                                      'primary_network': 'n1',
                                      'secondary_networks': []}],
                        'networks': [{'id': 'n1',
                                      'roles': ['database_network', 'control_network'],
                                      'site': 'nancy',
                                      'type': 'prod'},
                                     ]}},
  'registry': {'ceph': True,
               'ceph_id': 'discovery',
               'ceph_keyring': '/home/discovery/.ceph/ceph.client.discovery.keyring',
               'ceph_mon_host': ['ceph0.rennes.grid5000.fr',
                                 'ceph1.rennes.grid5000.fr',
                                 'ceph2.rennes.grid5000.fr'],
               'ceph_rbd': 'discovery_kolla_registry/datas',
               'type': 'none'},
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


def keystone_exp():
    sweeper = ParamSweeper(
      './sweeper',
      sweeps=sweep({
          'db':    DATABASES
        , 'delay': DELAYS
        , 'db-nodes': CLUSTER_SIZES
      }))

    while sweeper.get_remaining():
      combination = sweeper.get_next()
      logging.info("Treating combination %s" % pformat(combination))

      try:
        # Setup parameters
        conf = copy.deepcopy(CONF) # Make a deepcopy so we can run
                                   # multiple sweeps in parallels
        conf['g5k']['resources']['machines'][0]['nodes'] = combination['db-nodes']
        conf['tc']['constraints'][0]['delay'] = "%sms" % combination['delay']
        db = combination['db']

        # Let's get it started hun!
        j.deploy(conf, db, False)
        j.openstack(db)
        j.emulate(conf['tc'])
        j.rally(SCENARIOS, "keystone")
        j.backup()
        j.destroy()

        # Everything works well, mark combination as done
        sweeper.done(combination)

        # Put the latency back at its normal state
        j.conf['tc']['constraints'][0]['delay'] = '0ms'
        j.emulate(conf['tc'])
      except Exception as e:
        # Oh no, something goes wrong! Mark combination as cancel for
        # a later retry
        logging.error("Combination %s Failed with message %s" % (pformat(combination), e))
        sweeper.cancel(combination)


if __name__ == '__main__':
  # Note: Uncomment to do the initial reservation with the
  # MAX_CLUSTER_SIZE, and press CTRL+C when you see "waiting for
  # oargridjob ... to stop". Comment after reservation is done.
  # j.g5k(config=CONF)

  # Run experiment
  keystone_exp()
