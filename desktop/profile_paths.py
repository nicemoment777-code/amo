"""Use the same saved Windows profile for shortcuts, updates and background launch."""
from pathlib import Path


def profile_paths(env, registered):
    home=Path(env.get('SNOWBRICK_HOME') or registered.get('ProfileHome') or Path(env['LOCALAPPDATA'])/'SnowbrickPrinter')
    # An explicit QA/CLI home is an isolated profile unless data was explicitly supplied.
    data=Path(env.get('SNOWBRICK_DATA_DIR') or (None if env.get('SNOWBRICK_HOME') else registered.get('PrintingData')) or home/'printing')
    return home,data
