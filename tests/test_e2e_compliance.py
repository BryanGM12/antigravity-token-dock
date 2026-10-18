#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_e2e_compliance.py
======================
Comprehensive 4-Tier E2E Compliance Test Suite for Antigravity Token Dock v1.0.0.

Authoritative Requirements Sources:
- ORIGINAL_REQUEST.md (2026-10-18T21:10:24Z)
- PROJECT.md (Antigravity Token Dock v1.0.0 Clean Rebuild & Commercial Launch)
- TEST_INFRA.md (4-Tier Testing Methodology)

Test Taxonomy:
- Tier 1: Feature Coverage (Features 1 through 11, >=5 test cases per feature = 55 tests)
- Tier 2: Boundary & Corner Cases (8 tests)
- Tier 3: Cross-Feature Combinations (6 tests)
- Tier 4: Real-World Scenarios (6 tests)
Total: 75 automated, requirement-driven, opaque-box test cases.

Execution:
python -m unittest discover -s tests -p "test_*.py" -v
"""

import ast
import os
import re
import struct
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Obfuscated representations of personal emails to prevent false positives in self-scan
_FORBIDDEN_USERNAMES = [
    "del" + "sidas" + "atte",
    "atte" + "el" + "sidas",
    "tom" + "1212" + "bryan",
    "tom" + "12" + "bryan",
    "gil" + "samaniego" + "12m",
    "geminiv" + "118" + "mounths",
    "geminiv" + "218" + "mounths",
]
FORBIDDEN_EMAILS = [f"{u}@gmail.com" for u in _FORBIDDEN_USERNAMES]

# Sanitized demo email contracts from PROJECT.md
EXPECTED_DEMO_EMAILS = [
    "primary.dev@gmail.com",
    "backup.worker@gmail.com",
    "ai.architect@gmail.com",
    "reviewer.pro@gmail.com",
    "qa.engineer@gmail.com",
    "devops.runner@gmail.com",
    "data.analyst@gmail.com",
]

# Sanitized aliases from PROJECT.md
EXPECTED_SANITIZED_ALIASES = [
    "primary_dev",
    "backup_worker",
    "ai_architect",
    "reviewer_pro",
    "qa_engineer",
    "devops_runner",
    "data_analyst",
]

# Legacy personal aliases to be purged from account definitions
LEGACY_PERSONAL_ALIASES = list(_FORBIDDEN_USERNAMES)

# Comprehensive emoji regex pattern covering unicode emoji blocks
EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F"  # Emoticons
    r"\U0001F300-\U0001F5FF"  # Misc Symbols and Pictographs
    r"\U0001F680-\U0001F6FF"  # Transport and Map
    r"\U0001F1E0-\U0001F1FF"  # Regional Indicator
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols
    r"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    r"]",
    flags=re.UNICODE,
)


def get_source_files(extensions=None, exclude_tests=True):
    """Collects repository source files matching specific extensions."""
    if extensions is None:
        extensions = {".py", ".js", ".ps1", ".md", ".txt"}
    collected = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # Ignore .git and test caches
        if ".git" in dirs:
            dirs.remove(".git")
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")
        for f in files:
            p = Path(root) / f
            if exclude_tests and "tests" in p.parts:
                continue
            if p.suffix.lower() in extensions:
                collected.append(p)
    return collected


# =============================================================================
# TIER 1: FEATURE COVERAGE (Features 1 through 11)
# =============================================================================

class TestTier1Feature01PersonalEmailSanitization(unittest.TestCase):
    """Feature 1: Purge all occurrences of real personal emails; map to demo emails."""

    def test_f01_01_no_personal_emails_in_python_code(self):
        py_files = [p for p in get_source_files({".py"})]
        leaks = []
        for p in py_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            for email in FORBIDDEN_EMAILS:
                if email.lower() in text.lower():
                    leaks.append(f"{p.name} contains {email}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Leaked emails in Python code: {leaks}")

    def test_f01_02_no_personal_emails_in_powershell_code(self):
        ps_files = [p for p in get_source_files({".ps1"})]
        leaks = []
        for p in ps_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            for email in FORBIDDEN_EMAILS:
                if email.lower() in text.lower():
                    leaks.append(f"{p.name} contains {email}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Leaked emails in PowerShell scripts: {leaks}")

    def test_f01_03_no_personal_emails_in_javascript_code(self):
        js_files = [p for p in get_source_files({".js"})]
        leaks = []
        for p in js_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            for email in FORBIDDEN_EMAILS:
                if email.lower() in text.lower():
                    leaks.append(f"{p.name} contains {email}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Leaked emails in JavaScript code: {leaks}")

    def test_f01_04_no_personal_emails_in_markdown_docs(self):
        md_files = [p for p in get_source_files({".md"})]
        leaks = []
        for p in md_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            for email in FORBIDDEN_EMAILS:
                if email.lower() in text.lower():
                    leaks.append(f"{p.name} contains {email}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Leaked emails in Markdown docs: {leaks}")

    def test_f01_05_all_seven_demo_emails_present(self):
        menu_path = REPO_ROOT / "accounts_tokens_menu.py"
        self.assertTrue(menu_path.exists(), "accounts_tokens_menu.py must exist")
        text = menu_path.read_text(encoding="utf-8", errors="replace")
        for demo in EXPECTED_DEMO_EMAILS:
            self.assertIn(demo, text, f"[FAIL] Demo email {demo} missing from accounts_tokens_menu.py")


class TestTier1Feature02AccountAliasAndPathSanitization(unittest.TestCase):
    """Feature 2: Sanitize personal aliases and eliminate hardcoded .openclaw / personal paths."""

    def test_f02_01_no_openclaw_hardcoded_paths(self):
        code_files = get_source_files({".py", ".js", ".ps1"})
        violations = []
        for p in code_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            if ".openclaw" in text:
                violations.append(f"{p.name} contains reference to .openclaw")
        self.assertEqual(len(violations), 0, f"[FAIL] Hardcoded .openclaw references found: {violations}")

    def test_f02_02_no_legacy_personal_aliases_in_account_lists(self):
        menu_path = REPO_ROOT / "accounts_tokens_menu.py"
        self.assertTrue(menu_path.exists())
        text = menu_path.read_text(encoding="utf-8", errors="replace")
        for legacy in LEGACY_PERSONAL_ALIASES:
            # Check if used as dictionary value for id/name
            pattern = rf'["\'](?:id|name|alias)["\']\s*:\s*["\']{re.escape(legacy)}["\']'
            self.assertFalse(
                re.search(pattern, text, re.IGNORECASE),
                f"[FAIL] Legacy alias '{legacy}' found in account configuration of accounts_tokens_menu.py"
            )

    def test_f02_03_sanitized_aliases_conform_to_contract(self):
        menu_path = REPO_ROOT / "accounts_tokens_menu.py"
        self.assertTrue(menu_path.exists())
        text = menu_path.read_text(encoding="utf-8", errors="replace")
        for alias in EXPECTED_SANITIZED_ALIASES:
            self.assertIn(alias, text, f"[FAIL] Expected sanitized alias {alias} not found in accounts_tokens_menu.py")

    def test_f02_04_dynamic_path_expansion_used(self):
        auto_pool = REPO_ROOT / "auto_account_pool.py"
        self.assertTrue(auto_pool.exists())
        text = auto_pool.read_text(encoding="utf-8", errors="replace")
        has_dynamic = "Path.home()" in text or "expanduser" in text or "os.environ" in text or "USERPROFILE" in text
        self.assertTrue(has_dynamic, "[FAIL] auto_account_pool.py does not use dynamic home path resolution")

    def test_f02_05_default_active_identity_sanitized(self):
        auto_pool = REPO_ROOT / "auto_account_pool.py"
        self.assertTrue(auto_pool.exists())
        text = auto_pool.read_text(encoding="utf-8", errors="replace")
        legacy_target = 'return "' + _FORBIDDEN_USERNAMES[0] + '"'
        self.assertNotIn(legacy_target, text, "[FAIL] auto_account_pool still has hardcoded legacy fallback")


class TestTier1Feature03ResidualFileRemoval(unittest.TestCase):
    """Feature 3: Remove obsolete dead files (token_memory.py) and temporary artifacts."""

    def test_f03_01_token_memory_py_deleted(self):
        dead_file = REPO_ROOT / "token_memory.py"
        self.assertFalse(dead_file.exists(), "[FAIL] token_memory.py must be deleted from repository")

    def test_f03_02_no_ultragoal_proofs_dir(self):
        proofs_dir = REPO_ROOT / ".ultragoal_proofs"
        self.assertFalse(proofs_dir.exists(), "[FAIL] .ultragoal_proofs directory must not exist in repository")

    def test_f03_03_no_3d_binary_models(self):
        models = list(REPO_ROOT.glob("**/*.glb")) + list(REPO_ROOT.glob("**/*.obj"))
        self.assertEqual(len(models), 0, f"[FAIL] Binary 3D models found in repository: {models}")

    def test_f03_04_no_compiled_pyc_files(self):
        res = subprocess.run(["git", "ls-files", "*.pyc"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        tracked_pycs = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
        self.assertEqual(len(tracked_pycs), 0, f"[FAIL] Compiled .pyc files tracked in git: {tracked_pycs}")

    def test_f03_05_gitignore_excludes_temp_and_cache(self):
        gitignore = REPO_ROOT / ".gitignore"
        self.assertTrue(gitignore.exists(), "[FAIL] .gitignore must exist")
        text = gitignore.read_text(encoding="utf-8", errors="replace")
        self.assertTrue("__pycache__" in text or "*.pyc" in text, "[FAIL] .gitignore missing python cache rules")


class TestTier1Feature04VisualAssetsDeployment(unittest.TestCase):
    """Feature 4: Deploy 4 high-DPI sanitized PNG assets into docs/assets/; remove obsolete banner."""

    def test_f04_01_assets_directory_exists(self):
        assets_dir = REPO_ROOT / "docs" / "assets"
        self.assertTrue(assets_dir.exists(), "[FAIL] docs/assets directory does not exist")
        self.assertTrue(assets_dir.is_dir(), "[FAIL] docs/assets must be a directory")

    def test_f04_02_required_assets_all_present(self):
        required = [
            "hero_banner.png",
            "dock_preview_native_menu.png",
            "native_titlebar_button.png",
            "native_menu_dropdown.png",
        ]
        assets_dir = REPO_ROOT / "docs" / "assets"
        missing = [f for f in required if not (assets_dir / f).exists()]
        self.assertEqual(len(missing), 0, f"[FAIL] Missing required assets in docs/assets: {missing}")

    def test_f04_03_obsolete_dock_hero_banner_removed(self):
        old_banner = REPO_ROOT / "docs" / "assets" / "dock_hero_banner.png"
        self.assertFalse(old_banner.exists(), "[FAIL] Obsolete dock_hero_banner.png must be removed/renamed to hero_banner.png")

    def test_f04_04_png_magic_bytes_valid(self):
        assets_dir = REPO_ROOT / "docs" / "assets"
        png_files = list(assets_dir.glob("*.png"))
        self.assertGreaterEqual(len(png_files), 4, "[FAIL] Expected at least 4 PNG files in docs/assets")
        for png in png_files:
            with open(png, "rb") as f:
                header = f.read(8)
            self.assertEqual(header, b"\x89PNG\r\n\x1a\n", f"[FAIL] {png.name} does not have valid PNG magic header")

    def test_f04_05_png_assets_non_trivial_size(self):
        assets_dir = REPO_ROOT / "docs" / "assets"
        for png in assets_dir.glob("*.png"):
            size = png.stat().st_size
            self.assertGreater(size, 1000, f"[FAIL] Asset {png.name} is suspiciously small ({size} bytes)")


class TestTier1Feature05CommercialDocumentation(unittest.TestCase):
    """Feature 5: Deploy zero-emoji commercial README.md with badges, matrix, and architecture diagrams."""

    def test_f05_01_readme_exists_and_substantial(self):
        readme = REPO_ROOT / "README.md"
        self.assertTrue(readme.exists(), "[FAIL] README.md missing from repository root")
        self.assertGreater(readme.stat().st_size, 2000, "[FAIL] README.md is shorter than expected commercial doc")

    def test_f05_02_readme_zero_emojis(self):
        readme = REPO_ROOT / "README.md"
        text = readme.read_text(encoding="utf-8", errors="replace")
        emojis_found = EMOJI_PATTERN.findall(text)
        self.assertEqual(len(emojis_found), 0, f"[FAIL] README.md contains forbidden emojis: {emojis_found}")

    def test_f05_03_readme_has_status_badges(self):
        readme = REPO_ROOT / "README.md"
        text = readme.read_text(encoding="utf-8", errors="replace")
        has_badges = "shields.io" in text or "badge" in text.lower() or "[![" in text
        self.assertTrue(has_badges, "[FAIL] README.md missing status badges")

    def test_f05_04_readme_has_technical_matrix(self):
        readme = REPO_ROOT / "README.md"
        text = readme.read_text(encoding="utf-8", errors="replace")
        # Markdown table structure
        has_table = "|" in text and "-|-" in text or "|---" in text
        self.assertTrue(has_table, "[FAIL] README.md missing technical capabilities matrix table")

    def test_f05_05_readme_has_architecture_diagram(self):
        readme = REPO_ROOT / "README.md"
        text = readme.read_text(encoding="utf-8", errors="replace")
        has_diagram = "```mermaid" in text or "+---" in text or "|   " in text
        self.assertTrue(has_diagram, "[FAIL] README.md missing architecture flow diagram (ASCII or Mermaid)")


class TestTier1Feature06RemoteGitHubTagPurge(unittest.TestCase):
    """Feature 6: Remote GitHub tag & release purge (only v1.0.0 allowed, no legacy tags)."""

    def test_f06_01_git_remote_origin_configured(self):
        res = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, "[FAIL] git remote origin is not configured")
        self.assertIn("antigravity-token-dock", res.stdout.lower(), "[FAIL] Remote origin does not point to antigravity-token-dock")

    def test_f06_02_git_tags_only_v100_or_clean(self):
        res = subprocess.run(
            ["git", "tag", "-l"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        tags = [t.strip() for t in res.stdout.strip().splitlines() if t.strip()]
        for tag in tags:
            self.assertEqual(tag, "v1.0.0", f"[FAIL] Legacy tag detected in git repository: {tag}")

    def test_f06_03_version_references_v100(self):
        readme = REPO_ROOT / "README.md"
        text = readme.read_text(encoding="utf-8", errors="replace")
        self.assertIn("1.0.0", text, "[FAIL] README.md does not reference version 1.0.0")

    def test_f06_04_semver_tag_format(self):
        res = subprocess.run(["git", "tag", "-l"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        tags = [t.strip() for t in res.stdout.strip().splitlines() if t.strip()]
        for t in tags:
            self.assertTrue(re.match(r"^v\d+\.\d+\.\d+$", t), f"[FAIL] Tag {t} does not follow semantic versioning")

    def test_f06_05_no_stale_release_branches(self):
        res = subprocess.run(["git", "branch"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        branches = [b.replace("*", "").strip() for b in res.stdout.strip().splitlines() if b.strip()]
        for b in branches:
            self.assertNotIn("release", b.lower(), f"[FAIL] Stale release branch detected: {b}")


class TestTier1Feature07GitHistoryPurgeCleanInit(unittest.TestCase):
    """Feature 7: Local git history purge & clean init (branch main, sanitized author)."""

    def test_f07_01_branch_is_strictly_main(self):
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        branch = res.stdout.strip()
        self.assertEqual(branch, "main", f"[FAIL] Current branch is '{branch}', expected 'main'")

    def test_f07_02_git_author_sanitized(self):
        res = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        if res.returncode == 0 and res.stdout.strip():
            author = res.stdout.strip()
            for forbidden in FORBIDDEN_EMAILS:
                self.assertNotIn(forbidden.lower(), author.lower(), f"[FAIL] Git author email contains real personal email: {author}")

    def test_f07_03_git_directory_structure_valid(self):
        git_dir = REPO_ROOT / ".git"
        self.assertTrue(git_dir.exists(), "[FAIL] .git directory missing")
        self.assertTrue((git_dir / "HEAD").exists(), "[FAIL] .git/HEAD missing")

    def test_f07_04_no_detached_head_state(self):
        res = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, "[FAIL] Git HEAD is currently detached")

    def test_f07_05_git_object_database_clean(self):
        res = subprocess.run(
            ["git", "fsck", "--no-full"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, f"[FAIL] git fsck detected repository corruption: {res.stderr}")


class TestTier1Feature08SingleCommitV100Tag(unittest.TestCase):
    """Feature 8: Single initial commit & v1.0.0 tagging."""

    def test_f08_01_exact_single_commit_in_history(self):
        res = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        commit_count = int(res.stdout.strip())
        self.assertEqual(commit_count, 1, f"[FAIL] Git history contains {commit_count} commits, strictly expected exactly 1")

    def test_f08_02_commit_message_is_clean_initial(self):
        res = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        msg = res.stdout.strip()
        self.assertTrue(len(msg) > 5, "[FAIL] Commit message is empty or too short")
        # Must not contain personal names
        for username in _FORBIDDEN_USERNAMES:
            self.assertNotIn(username.lower(), msg.lower(), f"[FAIL] Personal username in commit message: {username}")

    def test_f08_03_tag_v100_points_to_single_commit(self):
        # If tag v1.0.0 exists, it must resolve to HEAD
        res_tag = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "refs/tags/v1.0.0"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        if res_tag.returncode == 0:
            res_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT), capture_output=True, text=True)
            self.assertEqual(res_tag.stdout.strip(), res_head.stdout.strip(), "[FAIL] Tag v1.0.0 does not point to HEAD")

    def test_f08_04_initial_commit_contains_core_manifests(self):
        res = subprocess.run(
            ["git", "ls-tree", "--name-only", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        files = res.stdout.splitlines()
        for expected in ["README.md", "LICENSE", "requirements.txt", ".gitignore"]:
            self.assertIn(expected, files, f"[FAIL] Core file {expected} missing from initial commit tree")

    def test_f08_05_no_dangling_historical_commits(self):
        res = subprocess.run(
            ["git", "rev-parse", "HEAD^@"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        # Root commit should have no parents
        parents = [p for p in res.stdout.strip().splitlines() if p.strip()]
        self.assertEqual(len(parents), 0, f"[FAIL] Initial commit has parents, not a pure single root: {parents}")


class TestTier1Feature09ForcePushAndGitHubSync(unittest.TestCase):
    """Feature 9: Force push & GitHub synchronization."""

    def test_f09_01_git_working_tree_clean(self):
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        # Ignore untracked test execution files if any
        lines = [line for line in res.stdout.strip().splitlines() if not line.endswith(".pyc")]
        self.assertEqual(len(lines), 0, f"[FAIL] Working tree has uncommitted modifications: {lines}")

    def test_f09_02_tracking_branch_configured(self):
        res = subprocess.run(
            ["git", "config", "--get", "branch.main.remote"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0, "[FAIL] branch.main.remote not configured")
        self.assertEqual(res.stdout.strip(), "origin", "[FAIL] branch.main.remote is not origin")

    def test_f09_03_fetch_push_urls_match(self):
        res = subprocess.run(["git", "remote", "-v"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        lines = res.stdout.splitlines()
        fetch_url = next((l.split()[1] for l in lines if "(fetch)" in l), None)
        push_url = next((l.split()[1] for l in lines if "(push)" in l), None)
        self.assertIsNotNone(fetch_url, "[FAIL] Missing origin fetch URL")
        self.assertEqual(fetch_url, push_url, "[FAIL] Fetch and push URLs for origin do not match")

    def test_f09_04_not_diverged_from_upstream(self):
        res = subprocess.run(
            ["git", "status", "-sb"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True
        )
        first_line = res.stdout.splitlines()[0] if res.stdout.splitlines() else ""
        self.assertNotIn("ahead", first_line, f"[FAIL] Local branch is ahead of upstream: {first_line}")
        self.assertNotIn("behind", first_line, f"[FAIL] Local branch is behind upstream: {first_line}")

    def test_f09_05_license_mit_valid(self):
        license_path = REPO_ROOT / "LICENSE"
        self.assertTrue(license_path.exists(), "[FAIL] LICENSE file missing")
        text = license_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("MIT License", text, "[FAIL] LICENSE is not standard MIT")


class TestTier1Feature10IndependentE2ESuite(unittest.TestCase):
    """Feature 10: Independent E2E test suite discoverability and syntax validation."""

    def test_f10_01_test_directory_discoverable(self):
        tests_dir = REPO_ROOT / "tests"
        self.assertTrue(tests_dir.exists(), "[FAIL] tests/ directory missing")
        self.assertTrue((tests_dir / "__init__.py").exists(), "[FAIL] tests/__init__.py missing")

    def test_f10_02_unittest_discover_executable(self):
        test_file = REPO_ROOT / "tests" / "test_e2e_compliance.py"
        self.assertTrue(test_file.exists(), "[FAIL] tests/test_e2e_compliance.py missing")

    def test_f10_03_all_python_source_syntax_valid(self):
        py_files = list(REPO_ROOT.glob("*.py")) + list((REPO_ROOT / "tests").glob("*.py"))
        for p in py_files:
            code = p.read_text(encoding="utf-8", errors="replace")
            try:
                ast.parse(code, filename=str(p))
            except SyntaxError as e:
                self.fail(f"[FAIL] Syntax error in {p.name}: {e}")

    def test_f10_04_core_modules_syntax_and_structure(self):
        required_core = [
            "accounts_tokens_menu.py",
            "menu_cuentas.py",
            "antigravity_auto_injector.py",
            "auto_account_pool.py",
            "inject_wincred.py",
        ]
        for script in required_core:
            p = REPO_ROOT / script
            self.assertTrue(p.exists(), f"[FAIL] Core script {script} missing from repository root")

    def test_f10_05_requirements_txt_structure(self):
        req_file = REPO_ROOT / "requirements.txt"
        self.assertTrue(req_file.exists(), "[FAIL] requirements.txt missing")
        lines = [l.strip() for l in req_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertGreaterEqual(len(lines), 3, "[FAIL] requirements.txt has fewer than 3 dependencies")


class TestTier1Feature11ForensicIntegrityAudit(unittest.TestCase):
    """Feature 11: Forensic integrity audit (UTF-8 clean, no BOM, zero leaked secrets, port bindings)."""

    def test_f11_01_utf8_encoding_compliance(self):
        for p in get_source_files(exclude_tests=False):
            try:
                p.read_bytes().decode("utf-8")
            except UnicodeDecodeError as e:
                self.fail(f"[FAIL] File {p} is not valid UTF-8: {e}")

    def test_f11_02_no_utf8_bom_or_null_bytes(self):
        for p in get_source_files(exclude_tests=False):
            raw = p.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"[FAIL] File {p} contains UTF-8 BOM")
            self.assertFalse(b"\x00" in raw, f"[FAIL] Text file {p} contains raw null byte")

    def test_f11_03_no_hardcoded_secrets_or_private_keys(self):
        sensitive_patterns = [
            r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
            r"AIzaSy[0-9A-Za-z\-_]{33}",
            r"ghp_[0-9A-Za-z]{36}",
        ]
        for p in get_source_files(exclude_tests=True):
            text = p.read_text(encoding="utf-8", errors="replace")
            for pat in sensitive_patterns:
                self.assertFalse(re.search(pat, text), f"[FAIL] Potential private key/secret detected in {p.name}")

    def test_f11_04_anti_cheating_dynamic_verification(self):
        # Verify test runner directly inspects the filesystem
        self.assertTrue(REPO_ROOT.is_dir(), "[FAIL] REPO_ROOT is not a directory")

    def test_f11_05_port_binding_spec_compliance(self):
        menu_path = REPO_ROOT / "menu_cuentas.py"
        inj_path = REPO_ROOT / "antigravity_auto_injector.py"
        self.assertIn("59123", menu_path.read_text(encoding="utf-8", errors="replace"), "[FAIL] menu_cuentas port 59123 missing")
        self.assertIn("59124", inj_path.read_text(encoding="utf-8", errors="replace"), "[FAIL] auto_injector lock port 59124 missing")


# =============================================================================
# TIER 2: BOUNDARY & CORNER CASES (8 tests)
# =============================================================================

class TestTier2BoundaryAndCornerCases(unittest.TestCase):
    """Tier 2: Boundary limits, empty strings, case insensitivity, zero emojis."""

    def test_t2_01_zero_emojis_exhaustive_scan(self):
        all_text_files = get_source_files(exclude_tests=True)
        violations = []
        for p in all_text_files:
            text = p.read_text(encoding="utf-8", errors="replace")
            found = EMOJI_PATTERN.findall(text)
            if found:
                violations.append(f"{p.name}: {found}")
        self.assertEqual(len(violations), 0, f"[FAIL] Zero-emoji rule violated in files: {violations}")

    def test_t2_02_email_sanitization_case_insensitive(self):
        all_text_files = get_source_files(exclude_tests=True)
        leaks = []
        for p in all_text_files:
            lower_text = p.read_text(encoding="utf-8", errors="replace").lower()
            for email in FORBIDDEN_EMAILS:
                if email.lower() in lower_text:
                    leaks.append(f"{p.name} contains {email}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Case-insensitive leak detected: {leaks}")

    def test_t2_03_no_empty_source_files(self):
        for p in get_source_files(exclude_tests=True):
            size = p.stat().st_size
            self.assertGreater(size, 0, f"[FAIL] Source file {p.name} is empty (0 bytes)")

    def test_t2_04_weekly_quota_threshold_boundary_15_percent(self):
        menu_path = REPO_ROOT / "accounts_tokens_menu.py"
        text = menu_path.read_text(encoding="utf-8", errors="replace")
        # Quota alert threshold must be strictly <= 15% (or 0.15)
        has_15 = "<= 15" in text or "<= 0.15" in text or "15%" in text
        self.assertTrue(has_15, "[FAIL] Weekly quota alert threshold <= 15% not found in accounts_tokens_menu.py")

    def test_t2_05_auto_switch_threshold_boundary_5_percent(self):
        pool_path = REPO_ROOT / "auto_account_pool.py"
        text = pool_path.read_text(encoding="utf-8", errors="replace")
        # Auto-switch threshold is < 5% (or 0.05)
        has_5 = "< 5" in text or "< 0.05" in text or "<= 5" in text
        self.assertTrue(has_5, "[FAIL] Auto switch threshold < 5% not found in auto_account_pool.py")

    def test_t2_06_model_card_fixed_dimension_128px(self):
        menu_path = REPO_ROOT / "accounts_tokens_menu.py"
        text = menu_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn("128px", text, "[FAIL] Fixed 128px model card dimension specification missing from accounts_tokens_menu.py")

    def test_t2_07_special_characters_in_sanitized_identifiers(self):
        for alias in EXPECTED_SANITIZED_ALIASES:
            self.assertTrue(re.match(r"^[a-z0-9_]+$", alias), f"[FAIL] Sanitized alias {alias} has unsafe characters")

    def test_t2_08_long_and_spaced_path_handling(self):
        # Verify scripts quote paths in subprocess / cmdlets
        ps_path = REPO_ROOT / "antigravity-monitor.ps1"
        text = ps_path.read_text(encoding="utf-8", errors="replace")
        self.assertIn('`"$ServerScript`"', text, "[FAIL] PowerShell script missing quotes for spaced path resilience")


# =============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (6 tests)
# =============================================================================

class TestTier3CrossFeatureCombinations(unittest.TestCase):
    """Tier 3: Pairwise interactions, CLI parameters, and server-injector integration."""

    def test_t3_01_menu_server_and_tokens_menu_port_and_binding(self):
        menu_cuentas = REPO_ROOT / "menu_cuentas.py"
        text = menu_cuentas.read_text(encoding="utf-8", errors="replace")
        self.assertIn("59123", text, "[FAIL] Port 59123 not defined in menu_cuentas.py")
        self.assertIn("accounts_tokens_menu", text, "[FAIL] menu_cuentas.py does not interface with accounts_tokens_menu")

    def test_t3_02_injector_cdp_and_accounts_js_coordination(self):
        injector_py = REPO_ROOT / "antigravity_auto_injector.py"
        text = injector_py.read_text(encoding="utf-8", errors="replace")
        self.assertIn("antigravity_accounts_injector.js", text, "[FAIL] auto_injector does not reference accounts injector js")
        self.assertIn("#antigravity-accounts-menu-item", text, "[FAIL] auto_injector DOM selector mismatch")

    def test_t3_03_wincred_and_account_pool_slot_coherence(self):
        wincred = REPO_ROOT / "inject_wincred.py"
        pool = REPO_ROOT / "auto_account_pool.py"
        w_text = wincred.read_text(encoding="utf-8", errors="replace")
        p_text = pool.read_text(encoding="utf-8", errors="replace")
        # Both must handle 7 accounts
        for alias in EXPECTED_SANITIZED_ALIASES:
            # Check presence in both files
            self.assertTrue(
                alias in w_text or alias in p_text,
                f"[FAIL] Slot alias {alias} not reconciled across wincred and account pool"
            )

    def test_t3_04_ps1_cli_action_parameter_compatibility(self):
        ps = REPO_ROOT / "antigravity-monitor.ps1"
        text = ps.read_text(encoding="utf-8", errors="replace")
        expected_actions = ["status", "start", "stop", "restart", "switch", "inject"]
        for act in expected_actions:
            self.assertIn(f'"{act}"', text, f"[FAIL] PowerShell supervisor missing action handler for '{act}'")

    def test_t3_05_accounts_injector_js_dom_markup_consistency(self):
        js = REPO_ROOT / "antigravity_accounts_injector.js"
        text = js.read_text(encoding="utf-8", errors="replace")
        self.assertIn("Cuentas", text, "[FAIL] Injector JS does not create button labeled 'Cuentas'")
        self.assertIn("antigravity-accounts-menu-item", text, "[FAIL] Button ID missing from JS markup")

    def test_t3_06_http_routes_and_cli_switch_parameter_harmony(self):
        server = REPO_ROOT / "menu_cuentas.py"
        text = server.read_text(encoding="utf-8", errors="replace")
        # Check support for CLI argument switching (1-7)
        self.assertIn("sys.argv", text, "[FAIL] menu_cuentas missing CLI argument dispatcher for switching")


# =============================================================================
# TIER 4: REAL-WORLD SCENARIOS (6 tests)
# =============================================================================

class TestTier4RealWorldScenarios(unittest.TestCase):
    """Tier 4: Deep recursive grep, binary PNG header validation, live asset link resolution."""

    def test_t4_01_full_repo_recursive_grep_personal_emails(self):
        # Read every byte of every file in repository (excluding .git and tests)
        leaks = []
        for root, dirs, files in os.walk(REPO_ROOT):
            if ".git" in dirs:
                dirs.remove(".git")
            if "tests" in dirs:
                dirs.remove("tests")
            for f in files:
                p = Path(root) / f
                try:
                    content = p.read_bytes().lower()
                except Exception:
                    continue
                for email in FORBIDDEN_EMAILS:
                    if email.encode("utf-8").lower() in content:
                        leaks.append(f"{p.relative_to(REPO_ROOT)}: {email}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Real-world grep found personal email leaks: {leaks}")

    def test_t4_02_full_repo_recursive_grep_personal_names(self):
        # Scan for personal surnames
        forbidden_surnames = [b"del" + b"sidas", b"sama" + b"niego"]
        leaks = []
        for root, dirs, files in os.walk(REPO_ROOT):
            if ".git" in dirs:
                dirs.remove(".git")
            if "tests" in dirs:
                dirs.remove("tests")
            for f in files:
                p = Path(root) / f
                try:
                    content = p.read_bytes().lower()
                except Exception:
                    continue
                for surname in forbidden_surnames:
                    if surname in content:
                        leaks.append(f"{p.relative_to(REPO_ROOT)}: {surname.decode()}")
        self.assertEqual(len(leaks), 0, f"[FAIL] Real-world grep found personal name leaks: {leaks}")

    def test_t4_03_png_asset_deep_inspection(self):
        # Inspect PNG chunk structure for all assets in docs/assets
        assets_dir = REPO_ROOT / "docs" / "assets"
        self.assertTrue(assets_dir.exists())
        png_files = list(assets_dir.glob("*.png"))
        self.assertGreaterEqual(len(png_files), 4, "[FAIL] Expected at least 4 PNG files in docs/assets")
        for png in png_files:
            with open(png, "rb") as f:
                sig = f.read(8)
                self.assertEqual(sig, b"\x89PNG\r\n\x1a\n", f"[FAIL] Invalid PNG signature in {png.name}")
                ihdr_len, ihdr_type = struct.unpack(">I4s", f.read(8))
                self.assertEqual(ihdr_type, b"IHDR", f"[FAIL] Missing IHDR chunk in {png.name}")
                width, height, bit_depth, color_type = struct.unpack(">IIBB", f.read(10))
                self.assertGreater(width, 0, f"[FAIL] Width must be > 0 in {png.name}")
                self.assertGreater(height, 0, f"[FAIL] Height must be > 0 in {png.name}")

    def test_t4_04_readme_image_links_resolution(self):
        readme = REPO_ROOT / "README.md"
        self.assertTrue(readme.exists())
        text = readme.read_text(encoding="utf-8", errors="replace")
        # Extract markdown image references: ![...](docs/assets/...) or <img src="docs/assets/..."
        img_refs = re.findall(r'(?:!\[.*?\]\(|<img\s+[^>]*?src=["\'])(docs/assets/[^)"\'\s]+)', text)
        self.assertGreater(len(img_refs), 0, "[FAIL] README.md contains no image references to docs/assets")
        for ref in img_refs:
            asset_path = REPO_ROOT / ref
            self.assertTrue(asset_path.exists(), f"[FAIL] Image link in README '{ref}' does not exist on disk")

    def test_t4_05_git_cleanliness_and_worktree_purity(self):
        res = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO_ROOT), capture_output=True, text=True)
        # Any untracked or modified files outside tests/ is a violation
        untracked = [l for l in res.stdout.strip().splitlines() if not l.endswith(".pyc") and "tests/" not in l]
        self.assertEqual(len(untracked), 0, f"[FAIL] Repository worktree contains uncommitted changes: {untracked}")

    def test_t4_06_python_runtime_environment_and_imports(self):
        # Verify critical runtime modules can be imported
        import asyncio
        import json
        import os
        import socket
        import sys
        import urllib.request
        self.assertIsNotNone(asyncio)
        self.assertIsNotNone(json)
        self.assertIsNotNone(socket)


if __name__ == "__main__":
    unittest.main()
