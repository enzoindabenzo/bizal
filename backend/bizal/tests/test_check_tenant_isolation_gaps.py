import ast
import builtins
import importlib
import os
import sys
import tempfile

import pytest

_TOOLING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _TOOLING_DIR)

import check_tenant_isolation as cti  # noqa: E402


def test_allowlist_import_error_falls_back_to_empty_dict():
    """
    Covers the `except ImportError: ALLOWLIST = {}` fallback at module
    import time, by forcing the `tenant_isolation_allowlist` import to
    fail and reloading the module.
    """
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'tenant_isolation_allowlist':
            raise ImportError('simulated missing allowlist module')
        return real_import(name, *args, **kwargs)

    builtins.__import__ = fake_import
    try:
        reloaded = importlib.reload(cti)
        assert reloaded.ALLOWLIST == {}
    finally:
        builtins.__import__ = real_import
        importlib.reload(cti)  # restore normal state for subsequent tests


def test_resolve_module_aliases_list_with_call_element():
    """Covers the `elif isinstance(elt, ast.Call)` branch inside a list-alias
    assignment, e.g. `_perms = [HasTenantFeature('x')]`."""
    source = (
        "from tenants.permissions import HasTenantFeature\n"
        "_perms = [HasTenantFeature('staff_accounts')]\n"
    )
    tree = ast.parse(source)
    aliases, list_aliases = cti.resolve_module_aliases(tree)
    assert list_aliases['_perms'] == ['HasTenantFeature']


def test_names_from_list_node_plain_name_not_in_list_aliases():
    """Covers `out.add(aliases.get(node.id, node.id))` for a bare Name node
    that isn't itself a list alias."""
    node = ast.Name(id='IsAuthenticated', ctx=ast.Load())
    result = cti.names_from_list_node(node, aliases={}, list_aliases={})
    assert result == {'IsAuthenticated'}


def test_names_from_list_node_tuple_element_is_list_alias():
    """Covers `out.update(list_aliases[elt.id])` when a Tuple element refers
    to a name that is itself a list alias."""
    source = "permission_classes = (_notifications_permissions,)\n"
    tree = ast.parse(source)
    assign = tree.body[0]
    tuple_node = assign.value
    list_aliases = {'_notifications_permissions': ['IsAuthenticated', 'TenantDomainOnly']}
    # Wrap the Name inside a Tuple to hit the Tuple branch explicitly.
    name_node = ast.Name(id='_notifications_permissions', ctx=ast.Load())
    tuple_wrapper = ast.Tuple(elts=[name_node], ctx=ast.Load())
    result = cti.names_from_list_node(tuple_wrapper, aliases={}, list_aliases=list_aliases)
    assert result == {'IsAuthenticated', 'TenantDomainOnly'}


def test_source_mentions_tenant_missing_lineno_returns_false():
    """Covers the early `return False` when a node lacks lineno/end_lineno."""
    class FakeNode:
        pass

    assert cti.source_mentions_tenant(FakeNode(), ['some source line']) is False


def test_classify_unknown_permission_class():
    """Covers the fallback `return "UNKNOWN"` for an unrecognized permission
    class name."""
    assert cti.classify({'SomeCustomPermissionClass'}) == 'UNKNOWN'


def test_scan_file_syntax_error_returns_empty_list(capsys):
    """Covers the SyntaxError branch in scan_file — a views.py with invalid
    Python must not crash the scan, just be skipped with a stderr warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        broken_path = os.path.join(tmpdir, 'views.py')
        with open(broken_path, 'w') as f:
            f.write("def broken(:\n    pass\n")
        result = cti.scan_file(broken_path, tmpdir)
    assert result == []
    captured = capsys.readouterr()
    assert 'SyntaxError' in captured.err
