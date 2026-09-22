"""Tests for composite toolset expansion in delegate_task intersection."""

import unittest

from tools.delegate_tool import _expand_parent_toolsets


class TestExpandParentToolsets(unittest.TestCase):
    """Verify _expand_parent_toolsets recognises individual toolsets within composites."""

    def test_composite_robo_cli_expands_web(self):
        """robo-cli includes web_search/web_extract → 'web' should be in expansion."""
        expanded = _expand_parent_toolsets({"robo-cli"})
        self.assertIn("web", expanded)
        self.assertIn("terminal", expanded)
        self.assertIn("browser", expanded)
        # Original composite is preserved
        self.assertIn("robo-cli", expanded)


    def test_intersection_with_expanded_composite(self):
        """End-to-end: requesting ['web'] from parent with ['robo-cli'] yields ['web']."""
        parent_toolsets = {"robo-cli"}
        expanded = _expand_parent_toolsets(parent_toolsets)
        toolsets = ["web"]
        child_toolsets = [t for t in toolsets if t in expanded]
        self.assertEqual(child_toolsets, ["web"])


if __name__ == "__main__":
    unittest.main()
