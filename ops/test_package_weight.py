import unittest
from package_weight import kilograms,label_weight

class WeightTests(unittest.TestCase):
    def test_only_explicit_units_and_total(self):
        self.assertEqual(kilograms('4520 г'),'4,52 кг')
        self.assertEqual(kilograms('4.520 kg'),'4,52 кг')
        self.assertEqual(label_weight('Вес, кг 4.52'),'4,52 кг')
        self.assertEqual(label_weight('Вес: 600 г'),'0,6 кг')
        self.assertEqual(label_weight('Вес: 1 кг; Общий вес: 2 кг'),'2 кг')
        for value in ['0 кг','-2 кг','2','неизвестно']:
            with self.assertRaises(ValueError): kilograms(value)
        for value in ['Число мест 2','Вес 2 кг Вес 3 кг']:
            with self.assertRaises(ValueError): label_weight(value)
