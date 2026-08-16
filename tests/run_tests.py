"""
Standalone test runner using standard library unittest.
Executes test cases in tests/ without external dependencies.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tests.test_models import test_article_model_schema, test_single_direct_report_schema
from tests.test_clustering import (
    test_embedder_output_shape,
    test_clustering_multi_source_debate,
    test_delayed_perspective_upgrade_matching,
    test_alias_and_graph_multi_source_clustering
)
from tests.test_synthesis import test_local_fallback_synthesizer_debate, test_synthesis_engine_end_to_end


class TestVersusBackend(unittest.TestCase):
    def test_01_models(self):
        test_article_model_schema()
        test_single_direct_report_schema()

    def test_02_clustering(self):
        test_embedder_output_shape()
        test_clustering_multi_source_debate()
        test_delayed_perspective_upgrade_matching()
        test_alias_and_graph_multi_source_clustering()

    def test_03_synthesis(self):
        test_local_fallback_synthesizer_debate()
        test_synthesis_engine_end_to_end()


if __name__ == "__main__":
    unittest.main(verbosity=2)
