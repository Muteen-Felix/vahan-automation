import unittest
from controller import WorkerController, ControlError, PROJECT, SERVICES

class FakeEngine:
    def __init__(self):
        self.items = {service: {'Id': service, 'State': 'running', 'Labels': {
            'com.docker.compose.project': PROJECT, 'com.docker.compose.service': service}}
            for service in [*SERVICES, 'api', 'postgres', 'web']}
        self.operations = []
    def containers(self):
        return [*self.items.values(), {'Id': 'foreign', 'State': 'running', 'Labels': {
            'com.docker.compose.project': 'another-project', 'com.docker.compose.service': 'runner'}}]
    def inspect(self, identifier):
        item = self.items[identifier]
        return {'Config': {'Labels': item['Labels']}, 'State': {'Health': {'Status': 'healthy'}}}
    def start(self, identifier):
        self.operations.append(('start', identifier)); self.items[identifier]['State'] = 'running'
    def stop(self, identifier):
        self.operations.append(('stop', identifier)); self.items[identifier]['State'] = 'exited'

class ControllerTest(unittest.TestCase):
    def test_five_containers_only_and_grow_back_to_eight(self):
        engine = FakeEngine(); controller = WorkerController(engine, idle=lambda _service: True)
        self.assertEqual(controller.apply(5)['runningCount'], 5)
        self.assertEqual(engine.operations, [('stop', service) for service in SERVICES[5:]])
        self.assertTrue(all(engine.items[service]['State'] == 'running' for service in ['api', 'postgres', 'web']))
        engine.operations.clear()
        self.assertEqual(controller.apply(8)['runningCount'], 8)
        self.assertEqual(engine.operations, [('start', service) for service in SERVICES[5:8]])
    def test_busy_worker_blocks_the_whole_stop_set(self):
        engine = FakeEngine(); controller = WorkerController(engine, idle=lambda service: service != 'runner-8')
        with self.assertRaises(ControlError): controller.apply(5)
        self.assertEqual(engine.operations, [])
    def test_invalid_counts_never_touch_docker(self):
        engine = FakeEngine(); controller = WorkerController(engine, idle=lambda _service: True)
        for count in [0, 11, True, '5', 5.5]:
            with self.assertRaises(ControlError): controller.apply(count)
        self.assertEqual(engine.operations, [])

if __name__ == '__main__': unittest.main(verbosity=2)
