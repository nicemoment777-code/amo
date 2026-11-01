import unittest
from pathlib import Path
from profile_paths import profile_paths


class ProfileTests(unittest.TestCase):
    def test_manual_launch_uses_registered_connected_profile(self):
        home,data=profile_paths({'LOCALAPPDATA':'local'},{'ProfileHome':'saved-home','PrintingData':'saved-orders'})
        self.assertEqual(home,Path('saved-home'));self.assertEqual(data,Path('saved-orders'))

    def test_explicit_profile_and_data_override_registration(self):
        home,data=profile_paths({'LOCALAPPDATA':'local','SNOWBRICK_HOME':'qa','SNOWBRICK_DATA_DIR':'qa-data'},{'ProfileHome':'live','PrintingData':'live-data'})
        self.assertEqual(home,Path('qa'));self.assertEqual(data,Path('qa-data'))

    def test_isolated_home_does_not_reuse_live_order_history(self):
        home,data=profile_paths({'LOCALAPPDATA':'local','SNOWBRICK_HOME':'qa'},{'ProfileHome':'live','PrintingData':'live-data'})
        self.assertEqual(data,Path('qa/printing'))

    def test_new_computer_uses_its_own_default_profile(self):
        self.assertEqual(profile_paths({'LOCALAPPDATA':'local'},{}),(Path('local/SnowbrickPrinter'),Path('local/SnowbrickPrinter/printing')))
