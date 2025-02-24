# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
from azure.core.exceptions import ResourceNotFoundError
from devtools_testutils import ResourceGroupPreparer
from keys_async_preparer import AsyncVaultClientPreparer
from keys_async_test_case import AsyncKeyVaultTestCase


def print(*args):
    assert all(arg is not None for arg in args)


def test_create_key_client():
    vault_url = "vault_url"
    # pylint:disable=unused-variable
    # [START create_key_client]

    from azure.identity.aio import DefaultAzureCredential
    from azure.keyvault.keys.aio import KeyClient

    # Create a KeyClient using default Azure credentials
    credential = DefaultAzureCredential()
    key_client = KeyClient(vault_url, credential)

    # [END create_key_client]


class TestExamplesKeyVault(AsyncKeyVaultTestCase):
    @ResourceGroupPreparer()
    @AsyncVaultClientPreparer(enable_soft_delete=True)
    @AsyncKeyVaultTestCase.await_prepared_test
    async def test_example_key_crud_operations(self, vault_client, **kwargs):
        key_client = vault_client.keys
        # [START create_key]

        from dateutil import parser as date_parse

        key_size = 2048
        key_ops = ["encrypt", "decrypt", "sign", "verify", "wrapKey", "unwrapKey"]
        expires = date_parse.parse("2050-02-02T08:00:00.000Z")

        # create a key with optional arguments
        key = await key_client.create_key("key-name", "RSA", size=key_size, key_operations=key_ops, expires=expires)

        print(key.id)
        print(key.name)
        print(key.key_material.kty)
        print(key.properties.enabled)
        print(key.properties.expires)

        # [END create_key]
        # [START create_rsa_key]

        # create an rsa key in a hardware security module
        key = await key_client.create_rsa_key("key-name", hsm=True, size=2048)

        print(key.id)
        print(key.name)
        print(key.key_material.kty)

        # [END create_rsa_key]
        # [START create_ec_key]

        # create an elliptic curve (ec) key
        key_curve = "P-256"
        ec_key = await key_client.create_ec_key("key-name", hsm=False, curve=key_curve)

        print(ec_key.id)
        print(ec_key.name)
        print(ec_key.key_material.kty)
        print(ec_key.key_material.crv)

        # [END create_ec_key]
        # [START get_key]

        # get the latest version of a key
        key = await key_client.get_key("key-name")

        # alternatively, specify a version
        key_version = key.properties.version
        key = await key_client.get_key("key-name", key_version)

        print(key.id)
        print(key.name)
        print(key.properties.version)
        print(key.key_material.kty)
        print(key.properties.vault_url)

        # [END get_key]
        # [START update_key]

        # update attributes of an existing key
        expires = date_parse.parse("2050-01-02T08:00:00.000Z")
        tags = {"foo": "updated tag"}
        updated_key = await key_client.update_key_properties(key.name, expires=expires, tags=tags)

        print(updated_key.properties.version)
        print(updated_key.properties.updated)
        print(updated_key.properties.expires)
        print(updated_key.properties.tags)
        print(updated_key.key_material.kty)

        # [END update_key]
        # [START delete_key]

        # delete a key
        deleted_key = await key_client.delete_key("key-name")

        print(deleted_key.name)

        # if the vault has soft-delete enabled, the key's
        # scheduled purge date, deleted_date and recovery id are set
        print(deleted_key.deleted_date)
        print(deleted_key.scheduled_purge_date)
        print(deleted_key.recovery_id)

        # [END delete_key]

    @ResourceGroupPreparer()
    @AsyncVaultClientPreparer(enable_soft_delete=True)
    @AsyncKeyVaultTestCase.await_prepared_test
    async def test_example_key_list_operations(self, vault_client, **kwargs):
        key_client = vault_client.keys

        for i in range(4):
            await key_client.create_ec_key("key{}".format(i), hsm=False)
        for i in range(4):
            await key_client.create_rsa_key("key{}".format(i), hsm=False)

        # [START list_keys]

        # list keys
        keys = key_client.list_keys()

        async for key in keys:
            print(key.id)
            print(key.created)
            print(key.name)
            print(key.updated)
            print(key.enabled)

        # [END list_keys]
        # [START list_key_versions]

        # get an iterator of all versions of a key
        key_versions = key_client.list_key_versions("key-name")

        async for key in key_versions:
            print(key.id)
            print(key.updated)
            print(key.properties.version)
            print(key.expires)

        # [END list_key_versions]
        # [START list_deleted_keys]

        # get an iterator of deleted keys (requires soft-delete enabled for the vault)
        deleted_keys = key_client.list_deleted_keys()

        async for key in deleted_keys:
            print(key.id)
            print(key.name)
            print(key.scheduled_purge_date)
            print(key.recovery_id)
            print(key.deleted_date)

        # [END list_deleted_keys]

    @ResourceGroupPreparer()
    @AsyncVaultClientPreparer()
    @AsyncKeyVaultTestCase.await_prepared_test
    async def test_example_keys_backup_restore(self, vault_client, **kwargs):
        key_client = vault_client.keys
        key_name = "test-key"
        await key_client.create_key(key_name, "RSA")
        # [START backup_key]

        # backup key
        key_backup = await key_client.backup_key(key_name)

        # returns the raw bytes of the backup
        print(key_backup)

        # [END backup_key]

        await key_client.delete_key(key_name)

        # [START restore_key]

        # restores a backup
        restored_key = await key_client.restore_key(key_backup)
        print(restored_key.id)
        print(restored_key.name)
        print(restored_key.properties.version)

        # [END restore_key]

    @ResourceGroupPreparer()
    @AsyncVaultClientPreparer(enable_soft_delete=True)
    @AsyncKeyVaultTestCase.await_prepared_test
    async def test_example_keys_recover(self, vault_client, **kwargs):
        key_client = vault_client.keys
        created_key = await key_client.create_key("key-name", "RSA")

        await key_client.delete_key(created_key.name)
        await self._poll_until_no_exception(
            key_client.get_deleted_key, created_key.name, expected_exception=ResourceNotFoundError
        )

        # [START get_deleted_key]

        # get a deleted key (requires soft-delete enabled for the vault)
        deleted_key = await key_client.get_deleted_key("key-name")
        print(deleted_key.name)

        # [END get_deleted_key]
        # [START recover_deleted_key]

        # recover deleted key to its latest version (requires soft-delete enabled for the vault)
        recovered_key = await key_client.recover_deleted_key("key-name")
        print(recovered_key.id)
        print(recovered_key.name)

        # [END recover_deleted_key]
