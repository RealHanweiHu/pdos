"""Journal new uploads; preserve exact readable historical registered byte references."""

from pdos_next.object_journal import JournaledLocalObjectStore
from pdos_next.object_storage import LocalPrivateObjectStore, StorageFailure


class OriginalStore(JournaledLocalObjectStore):
    def __init__(self, root):
        super().__init__(root)
        self._legacy = LocalPrivateObjectStore(root, max_bytes=8_388_608)
        from pdos_next.object_lifecycle_runtime import LocalReversibleLifecycleAdapter

        def unavailable_gate(*_args, **_kwargs):
            raise StorageFailure("LIFECYCLE_UNAVAILABLE", "生命周期执行未配置。")

        self.lifecycle_transport = LocalReversibleLifecycleAdapter(self, unavailable_gate)

    def read_original(self, reference):
        self.lifecycle_transport.ensure_readable(reference)
        return super().read_original(reference)

    def read_registered(self, reference, scope):
        """Caller holds the current product/ACL gate and supplied a registered DB ref."""
        try:
            self.lookup_original(reference, scope)
        except StorageFailure as failure:
            if failure.code != "JOURNAL_NOT_FOUND":
                raise
            from pdos_next.original_lifecycle.types import LifecycleScope

            self.lifecycle_transport.ensure_legacy_readable(
                reference, LifecycleScope(scope.tenant_id, scope.product_id)
            )
            return self._legacy.read_original(reference)
        return self.read_original(reference)
