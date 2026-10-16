import unittest
from print_order import grouped_print_order, article_text

def item(id, text, created=0):
    return {'id':id, 'composition':text, 'createdAt':created}

class PrintOrderTests(unittest.TestCase):
    def test_groups_by_label_count_not_units(self):
        values = [item(1,'Товар (A) - 99'), item(2,'Товар (B) - 1'), item(3,'Товар (B) - 1')]
        self.assertEqual([v['id'] for v in grouped_print_order(values)], [2,3,1])

    def test_multiple_articles_form_one_group_regardless_of_order(self):
        values = [item(3,'(C)'),item(2,'(B); (A)'),item(1,'(A); (B)')]
        self.assertEqual([v['id'] for v in grouped_print_order(values)], [1,2,3])

    def test_equal_groups_use_oldest_order_and_keep_group_together(self):
        values = [item(1,'(A)',10),item(2,'(B)',1),item(3,'(A)',2),item(4,'(B)',11)]
        self.assertEqual([v['id'] for v in grouped_print_order(values)], [2,4,3,1])

    def test_missing_articles_are_not_silently_printed(self):
        with self.assertRaises(ValueError):
            grouped_print_order([item(1,'Без артикула')])
        self.assertEqual(article_text('Товар ( A ) - 2; Другой (B) - 1'), 'A; B')

if __name__ == '__main__':
    unittest.main()
