"""Load unapplied modules only in this process and run the portable pure regression draft."""
import importlib
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path('/Users/huhanwei/Desktop/ai-native-R&D-platform')
SERVER = ROOT / 'pdos-next/server'
DRAFT = Path(__file__).resolve().parent
assert not any('DATABASE' in k or k.startswith(('PG', 'PDOS_ANN_')) for k in os.environ)
sys.path.insert(0, str(SERVER))
importlib.import_module('pdos_next.models')
package = importlib.import_module('pdos_next.enterprise_search')
for short, filename in [('tokenizer', 'tokenizer-draft.py'), ('query', 'query-draft.py')]:
    name = 'pdos_next.enterprise_search.' + short
    path = DRAFT / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if short == 'tokenizer':
        # Read the unchanged production dictionary/terms/stopwords in memory.
        module.__file__ = str(SERVER / 'pdos_next/enterprise_search/tokenizer.py')
    sys.modules[name] = module
    setattr(package, short, module)
    spec.loader.exec_module(module)

import pytest
raise SystemExit(pytest.main([
    '-q', str(DRAFT / 'test_query_grammar.py'),
    '--junitxml=' + str(DRAFT / 'draft-pure.xml'),
]))
