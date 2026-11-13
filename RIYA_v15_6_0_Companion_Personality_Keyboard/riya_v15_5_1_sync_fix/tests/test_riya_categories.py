import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from riya_categories import default_categories, validate_categories, classify_task


class CategoryRulesTests(unittest.TestCase):
    def test_default_four_categories_match_team_principles(self):
        categories = default_categories()
        self.assertEqual([x['id'] for x in categories], [
            'high_priority', 'delegatable', 'enjoyable_low_growth', 'detrimental'])
        self.assertIn('career', categories[0]['description'])
        self.assertIn('dislike', categories[1]['description'])

    def test_high_priority_uses_confirmed_attributes(self):
        result = classify_task({'enjoyment':'enjoyable','importance':'important','growth_impact':'positive'})
        self.assertEqual(result['category_id'], 'high_priority')
        self.assertFalse(result['needs_review'])

    def test_important_disliked_task_is_delegatable(self):
        result = classify_task({'enjoyment':'disliked','importance':'important','growth_impact':'positive'})
        self.assertEqual(result['category_id'], 'delegatable')

    def test_enjoyable_low_growth_task(self):
        result = classify_task({'enjoyment':'enjoyable','importance':'not_important','growth_impact':'low_or_neutral'})
        self.assertEqual(result['category_id'], 'enjoyable_low_growth')

    def test_detrimental_task(self):
        result = classify_task({'enjoyment':'disliked','importance':'not_important','growth_impact':'negative'})
        self.assertEqual(result['category_id'], 'detrimental')

    def test_unknown_facts_are_not_guessed(self):
        result = classify_task({'enjoyment':'unknown','importance':'unknown','growth_impact':'unknown'})
        self.assertIsNone(result['category_id'])
        self.assertTrue(result['needs_review'])

    def test_user_override_wins(self):
        result = classify_task({'enjoyment':'disliked','importance':'important','growth_impact':'positive'}, user_category='high_priority')
        self.assertEqual(result['category_id'], 'high_priority')
        self.assertEqual(result['source'], 'user_override')

    def test_category_labels_and_descriptions_are_customizable(self):
        categories = default_categories()
        categories[0]['label'] = 'My growth priorities'
        categories[0]['description'] = 'My own definition.'
        saved = validate_categories(categories)
        self.assertEqual(saved[0]['label'], 'My growth priorities')
        self.assertEqual(saved[0]['description'], 'My own definition.')

    def test_core_categories_cannot_be_removed(self):
        with self.assertRaises(ValueError):
            validate_categories(default_categories()[:-1])


if __name__ == '__main__':
    unittest.main()
