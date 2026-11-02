import contextlib
import io
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from dev.tools import dropbox_setup as setup


class DropboxSetupTests(unittest.TestCase):
    @patch.object(setup, "load_dotenv")
    @patch.object(setup, "app_key", return_value="public-key")
    @patch.object(setup, "client")
    @patch.object(setup, "verify")
    @patch.object(setup, "upload_local_file")
    def test_verify_cli_only_verifies_and_loads_root_configuration(self, upload, verify, client, key, dotenv):
        self.assertEqual(setup.main(["verify"]), 0)
        verify.assert_called_once_with(client.return_value.__enter__.return_value)
        upload.assert_not_called()
        dotenv.assert_called_once_with(Path(setup.__file__).resolve().parents[2] / ".env")

    @patch.object(setup, "load_dotenv")
    @patch.object(setup, "app_key", return_value="public-key")
    @patch.object(setup, "client")
    @patch.object(setup, "upload_local_file")
    def test_upload_cli_uses_explicit_paths(self, upload, client, key, dotenv):
        self.assertEqual(setup.main(["upload", "example.txt", "/example.txt"]), 0)
        upload.assert_called_once_with(
            client.return_value.__enter__.return_value, Path("example.txt"), "/example.txt"
        )

    def make_client(self, contents_match=True):
        dbx = Mock()
        uploaded = SimpleNamespace(id="id:test", rev="revision")
        dbx.files_upload.return_value = uploaded
        dbx.files_list_folder.side_effect = [
            SimpleNamespace(entries=[], has_more=True, cursor="cursor"),
            SimpleNamespace(entries=[], has_more=False),
        ]
        dbx.files_list_folder_continue.return_value = SimpleNamespace(
            entries=[uploaded], has_more=False
        )
        response = Mock()

        def download(_):
            response.content = dbx.files_upload.call_args.args[0] if contents_match else b"wrong"
            return uploaded, response

        dbx.files_download.side_effect = download
        return dbx, response

    def test_roundtrip_with_pagination_and_revision_safe_delete(self):
        dbx, response = self.make_client()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            setup.verify(dbx)
        self.assertIn("PASS all Dropbox file checks", output.getvalue())
        dbx.files_list_folder_continue.assert_called_once_with("cursor")
        dbx.files_delete_v2.assert_called_once_with("id:test", parent_rev="revision")
        self.assertTrue(dbx.files_upload.call_args.kwargs["strict_conflict"])
        response.close.assert_called_once()

    def test_corrupt_download_fails_and_cleans_up(self):
        dbx, response = self.make_client(contents_match=False)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(setup.SetupError):
            setup.verify(dbx)
        response.close.assert_called_once()
        dbx.files_delete_v2.assert_called_once_with("id:test", parent_rev="revision")

    def test_upload_failure_does_not_delete_anything(self):
        dbx = Mock()
        dbx.files_upload.side_effect = RuntimeError("upload failed")
        with self.assertRaises(RuntimeError):
            setup.verify(dbx)
        dbx.files_delete_v2.assert_not_called()

    def test_failed_deletion_confirmation_is_not_success(self):
        dbx, _ = self.make_client()
        dbx.files_list_folder.side_effect = None
        dbx.files_list_folder.return_value = SimpleNamespace(
            entries=[dbx.files_upload.return_value], has_more=False
        )
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(setup.SetupError):
            setup.verify(dbx)
        dbx.files_delete_v2.assert_called_once()

    @patch.dict(setup.os.environ, {"DROPBOX_APP_KEY": ""})
    def test_missing_app_key(self):
        with self.assertRaises(setup.SetupError):
            setup.app_key()

    @patch("dev.tools.dropbox_setup.keyring.set_password")
    @patch("dev.tools.dropbox_setup.getpass.getpass", return_value="code")
    @patch("dev.tools.dropbox_setup.webbrowser.open")
    @patch("dev.tools.dropbox_setup.dropbox.DropboxOAuth2FlowNoRedirect")
    def test_auth_uses_pkce_minimal_scopes_and_credential_store(self, factory, browser, prompt, store):
        factory.return_value.start.return_value = "https://www.dropbox.com/oauth2/authorize"
        factory.return_value.finish.return_value = SimpleNamespace(
            refresh_token="test-token", scope=" ".join(setup.SCOPES)
        )
        with contextlib.redirect_stdout(io.StringIO()) as output:
            setup.authenticate("public-key")
        factory.assert_called_once_with(
            "public-key", use_pkce=True, token_access_type="offline", scope=setup.SCOPES
        )
        store.assert_called_once_with(setup.SERVICE, "public-key", "test-token")
        self.assertNotIn("test-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
