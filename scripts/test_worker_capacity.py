"""Resource selection checks without changing Docker services."""
import unittest
from unittest.mock import patch

import worker_capacity as capacity


class ServerCapacityTests(unittest.TestCase):
    def assess(self, cpus=64, total=256, available=150, current=0, docker_cpus=2, docker_ram=4):
        with patch.object(capacity.os, 'cpu_count', return_value=cpus), \
                patch.object(capacity, '_host_memory', return_value=(total * capacity.GIB, int(available * capacity.GIB))), \
                patch.object(capacity, '_current_worker_stats', return_value=(current, None, None)), \
                patch.object(capacity, '_capture', return_value=f'{docker_cpus}|{docker_ram * capacity.GIB}'):
            return capacity.assess_worker_capacity()

    def test_large_server_uses_twenty_despite_smaller_docker_allocation(self):
        value = self.assess()
        self.assertEqual(value.recommended_workers, 20)
        self.assertEqual(value.host_cpus, 64)
        self.assertLess(value.docker_memory_worker_limit, value.recommended_workers)

    def test_server_cpu_reduces_count(self):
        self.assertEqual(self.assess(cpus=12).recommended_workers, 6)

    def test_available_server_ram_reduces_count(self):
        self.assertEqual(self.assess(total=16, available=4).recommended_workers, 2)

    def test_no_headroom_does_not_start_new_workers(self):
        self.assertEqual(self.assess(total=16, available=0.5).recommended_workers, 0)

    def test_existing_workers_are_preserved_when_memory_is_low(self):
        self.assertEqual(self.assess(total=16, available=0.5, current=3).recommended_workers, 3)

    def test_live_pool_above_target_is_not_automatically_removed(self):
        self.assertEqual(self.assess(current=25).recommended_workers, 25)

    def test_unavailable_host_data_fails_instead_of_using_docker(self):
        with patch.object(capacity, '_capture', return_value=f'12|{8 * capacity.GIB}'), \
                patch.object(capacity, '_current_worker_stats', return_value=(0, None, None)), \
                patch.object(capacity, '_host_memory', return_value=(None, None)):
            with self.assertRaisesRegex(RuntimeError, 'Run the launcher directly on the server'):
                capacity.assess_worker_capacity()


if __name__ == '__main__':
    unittest.main()
