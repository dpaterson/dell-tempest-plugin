#!/usr/bin/python

# (c) 2016 Dell
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_log import log as logging
from tempest import config
from tempest import test
from tempest.common import waiters
from tempest.scenario import manager

CONF = config.CONF

LOG = logging.getLogger(__name__, "dell-tempest-plugin")


class TestVolumeBasicOps(manager.ScenarioTest):

    """The test suite for volume basic operations

    This test case follows this basic set of operations:
    * Boot an instance
    * Create Volume
    * Attach Volume to VM instance
    * Write data to a Volume
    * Reboot VM
    * Verify persistent data
    """

    def setUp(self):
        super(TestVolumeBasicOps, self).setUp()

        self.image_ref = CONF.compute.image_ref
        self.flavor_ref = CONF.compute.flavor_ref
        self.run_ssh = CONF.validation.run_validation
        self.ssh_user = CONF.validation.image_ssh_user
        LOG.info('Starting test for i:{image}, f:{flavor}. '
                  'Run ssh: {ssh}, user: {ssh_user}'.format(
                      image=self.image_ref, flavor=self.flavor_ref,
                      ssh=self.run_ssh, ssh_user=self.ssh_user))

    #def tearDown(self):
        # LOG.info("tearDown, before super call _cleanups: %s" % self._cleanups)
        # self._cleanups = []
        # super(TestVolumeBasicOps, self).tearDown()
        # LOG.info("tearDown, after super call _cleanups: %s" % self._cleanups)

    @test.idempotent_id('761eea18-99c0-4ad2-ac69-7d38adca7bd5')
    @test.attr(type='dell')
    @test.services('volume')
    def test_volume_basic_ops(self):
        LOG.info("Begin test_volume_basic_ops!")
        keypair = self.create_keypair()
        self.security_group = self._create_security_group()
        security_groups = [{'name': self.security_group['name']}]
        self.md = {'meta1': 'data1', 'meta2': 'data2', 'metaN': 'dataN'}
        self.instance = self.create_server(
            image_id=self.image_ref,
            flavor=self.flavor_ref,
            key_name=keypair['name'],
            security_groups=security_groups,
            config_drive=CONF.compute_feature_enabled.config_drive,
            metadata=self.md,
            wait_until='ACTIVE')
        
        self._create_and_attach_volume()
        self._config_ssh_client(keypair)

        self._verify_volume()
        self._volume_clean_up(self.instance['id'], self.volume['id'])
        self.servers_client.delete_server(self.instance['id'])

    def _config_ssh_client(self, keypair):
        if self.run_ssh:
            # Obtain a floating IP
            self.fip = self.create_floating_ip(self.instance)['ip']
            self.ssh_client = self.get_remote_client(
                ip_address=self.fip,
                username=self.ssh_user,
                private_key=keypair['private_key'])

    def _verify_volume(self):
        LOG.info("Begin verify_volume.")
        if self.run_ssh:
            dev_name = "vdb"
            mount_path = "/vol"
    
            # create file system on volume and mount it
            self.ssh_client.make_fs(dev_name)
            self.ssh_client.exec_command("sudo mkdir " + mount_path)
            self.ssh_client.mount(dev_name, mount_path)

            # create file and assert it was created
            cmd = "sudo touch /vol/test.txt && sudo ls /vol/test.txt"
            status = self.ssh_client.exec_command(cmd)
            LOG.info(" XXXXXXXXXXXXXXXXXXXXXXXXXreturn status from touch and ls command: %s" % status)
            self.assertEqual("/vol/test.txt\n", status, "created test.txt")

            # reboot instance and wait
            self.servers_client.reboot_server(self.instance['id'], type='SOFT')
            waiters.wait_for_server_status(self.servers_client,
                                           self.instance['id'], 'ACTIVE')
            # re-mount volume
            self.ssh_client.mount(dev_name, mount_path)
            LOG.info("Instance restarted and volume re-mounted.")

            # verify file is still there once volume is re-mounted
            status = self.ssh_client.exec_command("sudo ls /vol/test.txt")
            LOG.info("return status from ls command post reboot: %s" % status)
            self.assertEqual("/vol/test.txt\n", status,
                             "test.txt survived reboot.")

    def _create_and_attach_volume(self):
        self.volume = self.create_volume()
        v_id = self.volume['id']
        v_kwargs = {"volumeId": v_id, "device": "/dev/vdb"}

        status = self.servers_client.attach_volume(self.instance['id'],
                                                   **v_kwargs)
        LOG.info("attach_volume status: %s" % str(status))
        
        waiters.wait_for_volume_status(self.volumes_client,
                                       v_id, 'in-use')
        LOG.info("Done attaching volume:{}.".format([v_id])) 

    def _volume_clean_up(self, server_id, volume_id):
        body = self.volumes_client.show_volume(volume_id)['volume']
        LOG.info("_volume_clean_up show_volume body: %s"
               % str(body))
        if body['status'] == 'in-use':
            self.servers_client.detach_volume(server_id, volume_id)

            waiters.wait_for_volume_status(self.volumes_client,
                                           volume_id, 'available')
        self.volumes_client.delete_volume(volume_id)
