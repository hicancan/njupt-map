import unittest

from src.map.build_authored import build_network, routing_target_id


def feature(ident, kind, coordinates, parent=None, geometry='Point'):
    properties={'id':ident,'kind':kind}
    if parent is not None:
        properties['parent']=parent
    return {'type':'Feature','properties':properties,
            'geometry':{'type':geometry,'coordinates':coordinates}}


class RoutingTargetsTest(unittest.TestCase):
    def setUp(self):
        self.building=feature('building','building',[118.92,32.11])
        self.entrance=feature('entrance','entrance',[118.92,32.11],'building')
        self.entities=[self.building,self.entrance,
            feature('floor','floor',[118.92,32.11],'building'),
            feature('room-a','room',[118.92001,32.11],'floor'),
            feature('room-b','room',[118.92002,32.11],'floor'),
            feature('inside','place',[118.92003,32.11],'building'),
            feature('outside','place',[118.921,32.11])]
        self.by_id={f['properties']['id']:f for f in self.entities}

    def test_indoor_identity_is_distinct_from_road_access(self):
        for ident in ('building','floor','room-a','room-b','inside'):
            self.assertEqual(routing_target_id(ident,self.by_id),'building')
        self.assertEqual(routing_target_id('entrance',self.by_id),'entrance')
        self.assertEqual(routing_target_id('outside',self.by_id),'outside')

    def test_network_does_not_publish_fictitious_indoor_targets(self):
        ways=[feature('way','footway',[[118.92,32.11],[118.921,32.11]],geometry='LineString')]
        network,_,_=build_network(ways,[self.entrance],[self.building],entities=self.entities)
        self.assertEqual(set(network['targets']),{'building','entrance','outside'})
        self.assertEqual(network['targets']['building'],network['targets']['entrance'])
        for ident in self.by_id:
            self.assertIn(routing_target_id(ident,self.by_id),network['targets'])

    def test_invalid_indoor_parent_chains_are_rejected(self):
        self.by_id['floor']['properties']['parent']='room-a'
        with self.assertRaisesRegex(ValueError,'parent cycle'):
            routing_target_id('room-a',self.by_id)
        self.by_id['floor']['properties'].pop('parent')
        with self.assertRaisesRegex(ValueError,'no building'):
            routing_target_id('room-a',self.by_id)
        self.by_id['floor']['properties']['parent']='missing'
        with self.assertRaisesRegex(ValueError,'unknown entity parent'):
            routing_target_id('room-a',self.by_id)


if __name__=='__main__':
    unittest.main()
