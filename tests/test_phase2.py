"""Phase 2: dependencies, bounded revision rounds, delegation, reviews that claim no scope."""

import json
import threading
import time
import unittest.mock

from axon import integrate, runtime
from test_axon import DONE, AxonTest, edit, step


def verdict(status, summary):
    return step("mcp", tool="report_result", args={"status": status, "summary": summary})


class Dependencies(AxonTest):
    def add_after(self, spec, scope, after):
        tid, dup = runtime.add_task(self.store, "p", "fake", spec, scope, after=after)
        self.assertIsNone(dup)
        return tid

    def test_dependent_task_waits_then_starts_from_the_dependency_result(self):
        a = self.add(edit("src/a/x.py") + DONE, scope=["src/a"])
        b = self.add_after(edit("src/b/y.py") + DONE, ["src/b"], a)  # disjoint scope: only the dependency orders them
        self.run_all()
        ta, tb = self.task(a), self.task(b)
        self.assertEqual((ta["status"], tb["status"]), ("COMPLETED", "COMPLETED"))
        self.assertEqual(tb["base"], ta["head"])
        started = {r["task"]: r["started"] for r in self.store.q("select task, started from attempts")}
        ended = {r["task"]: r["ended"] for r in self.store.q("select task, ended from attempts")}
        self.assertGreaterEqual(started[b], ended[a])
        self.assertEqual(self.shown(f"{b}-1", "src/a/x.py"), "x\n")  # b's checkout contained a's work

    def test_a_task_that_needs_several_results_starts_from_all_of_them_merged(self):
        a = self.add(edit("src/a/x.py") + DONE, scope=["src/a"])
        b = self.add(edit("src/b/y.py") + DONE, scope=["src/b"])
        c, dup = runtime.add_task(self.store, "p", "fake", edit("src/c/z.py") + DONE, ["src/c"], after=a, needs=[b])
        self.assertIsNone(dup)
        self.run_all()
        self.assertEqual(self.task(c)["status"], "COMPLETED")
        self.assertNotIn(self.task(c)["base"], (self.task(a)["head"], self.task(b)["head"]))  # a merge of both
        self.assertEqual((self.shown(f"{c}-1", "src/a/x.py"), self.shown(f"{c}-1", "src/b/y.py")), ("x\n", "x\n"))

    def test_results_that_conflict_fail_the_dependent_with_the_files(self):
        a = self.add(edit("src/a/x.py", "one\n") + edit("shared.txt", "one\n") + DONE, scope=["src/a", "shared.txt"])
        b = self.add(edit("src/b/y.py") + edit("shared.txt", "two\n") + DONE, scope=["src/b", "shared.txt"])
        c, _ = runtime.add_task(self.store, "p", "fake", DONE, ["src/c"], after=a, needs=[b])
        end = time.time() + 20
        while time.time() < end and self.task(c)["status"] != "FAILED":
            self.rt.tick()
            time.sleep(0.2)
        for th in self.rt.threads:
            th.join(20)
        self.assertEqual(self.task(c)["status"], "FAILED")
        self.assertIn("shared.txt", self.task(c)["note"])

    def test_a_failed_dependency_keeps_the_dependent_queued_and_unstarted(self):
        a = self.add(step("crash", code=3), scope=["src/a"])
        b = self.add_after(edit("src/b/y.py") + DONE, ["src/b"], a)
        end = time.time() + 8
        while time.time() < end:
            self.rt.tick()
            time.sleep(0.2)
        for th in self.rt.threads:
            th.join(20)
        self.assertEqual(self.task(a)["status"], "FAILED")
        self.assertEqual(self.task(b)["status"], "QUEUED")
        self.assertEqual(self.store.q("select 1 from attempts where task = ?", b), [])

    def test_dependency_must_be_an_implementation_task_in_the_same_project(self):
        with self.assertRaises(ValueError):
            runtime.add_task(self.store, "p", "fake", DONE, ["src"], after=9999)

    def test_siblings_that_are_only_valid_with_their_repair_integrate_as_a_group(self):
        self.project({"unique": 'test -z "$(cat src/*/w.txt 2>/dev/null | sort | uniq -d)"'})
        a = self.add(edit("src/a/w.txt", "w\n") + DONE, scope=["src/a"])
        b = self.add(edit("src/b/w.txt", "w\n") + DONE, scope=["src/b"])
        c, _ = runtime.add_task(self.store, "p", "fake", step("shell", cmd="echo v > src/b/w.txt") + DONE, ["src/b"], after=a, needs=[b])
        self.run_all()
        integrate.integrate(self.rt, a)
        with self.assertRaisesRegex(integrate.IntegrationError, "checks failed"):
            integrate.integrate(self.rt, b)  # a duplicate of a's line, repaired only by c
        with self.assertRaisesRegex(integrate.IntegrationError, f"builds on task {b}"):
            integrate.integrate(self.rt, c)
        self.assertTrue(integrate.integrate(self.rt, b, c))
        with self.assertRaisesRegex(integrate.IntegrationError, "already in"):
            integrate.integrate(self.rt, b, c)

    def test_integrating_tasks_in_order_groups_the_ones_that_only_pass_together(self):
        from axon import brainstorm
        self.project({"unique": 'test -z "$(cat src/*/w.txt 2>/dev/null | sort | uniq -d)"'})
        a = self.add(edit("src/a/w.txt", "w\n") + DONE, scope=["src/a"])
        b = self.add(edit("src/b/w.txt", "w\n") + DONE, scope=["src/b"])
        c, _ = runtime.add_task(self.store, "p", "fake", step("shell", cmd="echo v > src/b/w.txt") + DONE, ["src/b"], after=a, needs=[b])
        self.run_all()
        self.assertEqual(brainstorm.integrate_tasks(self.rt, [a, b, c]), [[a], [b, c]])
        self.assertEqual(brainstorm.integrate_tasks(self.rt, [a, b, c]), [])  # everything is in already

    def test_a_dependent_cannot_be_integrated_before_its_dependency(self):
        a = self.add(edit("src/a/x.py") + DONE, scope=["src/a"])
        b = self.add_after(edit("src/b/y.py") + DONE, ["src/b"], a)
        self.run_all()
        with self.assertRaisesRegex(integrate.IntegrationError, f"builds on task {a}"):
            integrate.integrate(self.rt, b)
        integrate.integrate(self.rt, a)
        self.assertTrue(integrate.integrate(self.rt, b))


class Revision(AxonTest):
    def reviewed(self, status="failed", summary="src/x.py:1 wrong"):
        tid = self.add(edit("src/x.py") + DONE)
        self.run_all()
        runtime.request_review(self.store, tid, "fake", verdict(status, summary))
        self.run_all()
        return tid

    def test_revision_starts_from_the_reviewed_commit_with_the_findings(self):
        tid = self.reviewed()
        rid, dup = runtime.revise(self.store, tid)
        self.assertIsNone(dup)
        r = self.task(rid)
        self.assertEqual((r["base"], r["round"], r["agent"]), (self.task(tid)["head"], 1, "fake"))
        self.assertIn("src/x.py:1 wrong", r["context"])
        self.run_all()
        self.assertEqual(self.task(rid)["status"], "COMPLETED")
        prompt = (self.tmp / "home" / "attempts" / f"{rid}-1" / "prompt.txt").read_text()
        self.assertIn("Reviewer findings on your previous result", prompt)
        self.assertNotIn("Already completed in this scope", prompt)  # the task being revised is not "done, do not redo"
        self.assertEqual(runtime.revise(self.store, tid)[1], rid)  # asking twice is the same work

    def test_only_a_change_request_on_the_current_result_can_be_revised(self):
        approved = self.reviewed("done", "fine")
        with self.assertRaisesRegex(ValueError, "does not ask for changes"):
            runtime.revise(self.store, approved)
        unreviewed = self.add(edit("src/z.py") + DONE)
        self.run_all()
        with self.assertRaisesRegex(ValueError, "does not ask for changes"):
            runtime.revise(self.store, unreviewed)

    def test_rounds_are_bounded_and_an_old_approval_does_not_cover_the_revision(self):
        cfg = self.tmp / "cfg" / "config.toml"
        cfg.write_text(cfg.read_text().replace("max_attempts = 2", "max_attempts = 2\nreview_rounds = 1"))
        self.rt = runtime.Runtime(self.store)
        tid = self.reviewed()
        rid, _ = runtime.revise(self.store, tid)
        self.run_all()
        runtime.request_review(self.store, rid, "fake", verdict("failed", "still wrong"))
        self.run_all()
        with self.assertRaisesRegex(ValueError, "revision limit reached"):
            runtime.revise(self.store, rid)
        self.assertFalse(runtime.review_approved(self.store, rid, self.task(tid)["head"]))
        self.assertFalse(runtime.review_approved(self.store, rid, self.task(rid)["head"]))


class Delegation(AxonTest):
    def tool(self, t, **args):
        return self.rt._delegate(self.task(t), args)

    def test_agent_delegates_follow_up_work_that_starts_after_it_finishes(self):
        child_spec = edit("src/d.py") + DONE
        parent = self.add(step("mcp", tool="delegate", args={"title": "more", "spec": child_spec, "scope": ["src/d.py"]})
                          + edit("src/p.py") + DONE)
        self.run_all()
        (child,) = self.store.q("select * from tasks where parent = ?", parent)
        self.assertEqual((child["after"], child["status"], child["base"]), (parent, "COMPLETED", self.task(parent)["head"]))
        self.assertEqual(self.shown(f"{child['id']}-1", "src/p.py"), "x\n")  # it started from the parent's result

    def test_delegation_is_bounded(self):
        parent = self.add(step("hang"), scope=["src/a"])
        spec = DONE
        self.assertTrue(self.tool(parent, title="t", spec=spec, scope=["src/a/one"])[0])
        ok, msg = self.tool(parent, title="t", spec=spec, scope=["src/other"])
        self.assertFalse(ok)
        self.assertIn("scope must stay inside src/a", msg)
        self.assertFalse(self.tool(parent, title="t", spec="", scope=["src/a"])[0])
        self.assertTrue(self.tool(parent, title="t2", spec=spec + "# 2\n", scope=["src/a"])[0])
        self.assertTrue(self.tool(parent, title="t3", spec=spec + "# 3\n", scope=["src/a"])[0])
        self.assertIn("limit", self.tool(parent, title="t4", spec=spec + "# 4\n", scope=["src/a"])[1])
        (child, *_) = self.store.q("select * from tasks where parent = ?", parent)
        self.assertEqual(self.rt._delegate(child, {"title": "x", "spec": spec, "scope": ["src/a"]}),
                         (False, "this task cannot delegate"))

    def test_a_review_neither_delegates_nor_blocks_implementation(self):
        done = self.add(edit("src/x.py") + DONE)
        self.run_all()
        rid, _ = runtime.request_review(self.store, done, "fake", step("hang"))
        other = self.add(step("hang"))  # scope src: a review claims no scope, so both run together
        self.rt.tick()
        self.wait(lambda: self.task(rid)["status"] == "RUNNING" and self.task(other)["status"] == "RUNNING")
        self.assertEqual(self.rt._delegate(self.task(rid), {"title": "x", "spec": DONE, "scope": ["src"]}),
                         (False, "this task cannot delegate"))
        runtime.stop_task(self.store, rid)
        runtime.stop_task(self.store, other)
        for th in self.rt.threads:
            th.join(30)


class AskPeer(AxonTest):
    """claude <-> codex questions, with the fake agent standing in for both (PEER maps it to itself)."""

    def setUp(self):
        super().setUp()
        self.peer = unittest.mock.patch.dict(runtime.PEER, {"fake": "fake"})
        self.peer.start()
        self.addCleanup(self.peer.stop)
        self.live = True
        threading.Thread(target=self.tick_while_live, daemon=True).start()  # the runner, while the test asks by hand
        self.addCleanup(setattr, self, "live", False)

    def tick_while_live(self):
        while self.live:
            self.rt.tick()
            time.sleep(0.2)

    def test_agent_asks_its_peer_and_gets_the_answer_back(self):
        question = verdict("done", "use the cache")  # the fake peer reads its question as its script
        asker = self.add(step("mcp", tool="ask_peer", args={"question": question}) + edit("src/p.py") + DONE)
        self.run_all()
        (ask,) = self.store.q("select * from tasks where kind = 'ask'")
        self.assertEqual((self.task(asker)["status"], ask["status"], ask["target"]), ("COMPLETED", "COMPLETED", asker))
        self.assertIn("use the cache", runtime.attempt_log(f"{asker}-1").read_text())  # the asker saw the answer
        with self.assertRaises(ValueError):  # a question is not a result
            runtime.request_review(self.store, ask["id"], "fake")
        with self.assertRaises(ValueError):
            runtime.apply_result(self.store, ask["id"])

    def test_questions_are_bounded_and_only_for_implementation_tasks(self):
        asker = self.add(step("hang"))
        self.wait(lambda: self.store.one("select 1 from attempts where task = ? and status = 'running'", asker))
        aid = f"{asker}-1"
        for i in range(3):
            self.assertTrue(self.rt._ask_peer(self.task(asker), aid, {"question": verdict("done", f"a{i}")})[0])
        self.assertIn("limit", self.rt._ask_peer(self.task(asker), aid, {"question": verdict("done", "a3")})[1])
        ask = self.store.one("select * from tasks where kind = 'ask'")
        self.assertEqual(self.rt._ask_peer(ask, aid, {"question": "q"}), (False, "this task cannot ask a peer"))
        self.assertFalse(self.rt._ask_peer(self.task(asker), aid, {"question": " "})[0])
        runtime.stop_task(self.store, asker)
        for th in self.rt.threads:
            th.join(30)

    def test_a_peer_that_never_answers_is_given_up_on(self):
        self.rt.cfg["limits"]["ask_timeout"] = 2
        asker = self.add(step("hang"))
        self.wait(lambda: self.store.one("select 1 from attempts where task = ? and status = 'running'", asker))
        ok, msg = self.rt._ask_peer(self.task(asker), f"{asker}-1", {"question": step("hang")})
        self.assertFalse(ok)
        self.assertIn("did not answer", msg)
        runtime.stop_task(self.store, asker)
        for th in self.rt.threads:
            th.join(30)
        self.assertIn(self.store.one("select status from tasks where kind = 'ask'")["status"], ("CANCELLED", "FAILED"))


class IntegrationReview(AxonTest):
    def setUp(self):
        super().setUp()
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text().replace("protected", "require_review = true\nprotected", 1))

    def approved_task(self, path):
        tid = self.add(edit(path) + DONE, scope=[path.rsplit("/", 1)[0]])
        self.run_all()
        runtime.request_review(self.store, tid, "fake", verdict("done", "ok"))
        self.run_all()
        return tid

    def review_integration(self, status, summary):
        rid, dup = runtime.request_integration_review(self.store, "p", "fake", verdict(status, summary))
        self.assertIsNone(dup)
        self.run_all()
        return rid

    def test_a_merge_of_approved_tasks_needs_its_own_review_before_promote(self):
        a, b = self.approved_task("src/a/x.py"), self.approved_task("src/b/y.py")
        integrate.integrate(self.rt, a)
        self.assertTrue(integrate.status(self.store, "p")["can_promote"])  # a fast-forward of the reviewed commit
        tip = integrate.integrate(self.rt, b)  # a real merge commit nobody has reviewed
        st = integrate.status(self.store, "p")
        self.assertEqual((st["can_promote"], st["review_needed"]), (False, True))
        with self.assertRaisesRegex(integrate.IntegrationError, "integration commit"):
            integrate.promote(self.store, "p")
        rid = self.review_integration("done", "the two fit together")
        prompt = (self.tmp / "home" / "attempts" / f"{rid}-1" / "prompt.txt").read_text()
        self.assertIn(f"Task {a}:", prompt)
        self.assertIn(f"Task {b}:", prompt)
        self.assertIn("+x", prompt)
        self.assertIn("work together after the merge", prompt)
        self.assertEqual(self.task(rid)["base"], tip)
        self.assertEqual(runtime.reviews(self.store)[0]["integration"], True)
        self.assertTrue(integrate.status(self.store, "p")["can_promote"])
        self.assertEqual(integrate.promote(self.store, "p"), tip)

    def test_a_change_request_blocks_and_new_integration_makes_the_approval_stale(self):
        a, b, c = (self.approved_task(f"src/{n}/f.py") for n in "abc")
        integrate.integrate(self.rt, a)
        integrate.integrate(self.rt, b)
        self.review_integration("failed", "src/b/f.py:1 conflicts with a")
        self.assertFalse(integrate.status(self.store, "p")["can_promote"])
        self.review_integration("done", "fixed")
        self.assertTrue(integrate.status(self.store, "p")["can_promote"])
        integrate.integrate(self.rt, c)  # the commit changed: the approval no longer covers it
        self.assertTrue(integrate.status(self.store, "p")["review_needed"])

    def test_nothing_to_review_before_anything_is_integrated(self):
        with self.assertRaisesRegex(ValueError, "nothing in the integration branch"):
            runtime.request_integration_review(self.store, "p", "fake")


class Rollback(AxonTest):
    def test_discard_drops_the_integration_branch_and_tasks_can_be_integrated_again(self):
        tid = self.add(edit("src/x.py") + DONE)
        self.run_all()
        tip = integrate.integrate(self.rt, tid)
        with self.assertRaisesRegex(integrate.IntegrationError, "changed"):
            integrate.discard(self.store, "p", expected="0" * 40)
        self.assertEqual(integrate.discard(self.store, "p", expected=tip), tip)
        self.assertEqual(self.git("rev-parse", "--verify", "-q", "refs/axon/integration/p").strip(), "")
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        self.assertEqual(integrate.status(self.store, "p")["reason"], "nothing to promote")
        with self.assertRaisesRegex(integrate.IntegrationError, "no integration branch"):
            integrate.discard(self.store, "p")
        self.assertEqual(integrate.integrate(self.rt, tid), tip)


class TaskChecks(AxonTest):
    def setUp(self):
        super().setUp()
        self.project({"a": "test -f src/a/a.py", "b": "test -f src/b/b.py"})  # each half needs only its own file

    def add_with(self, path, scope, checks):
        tid, dup = runtime.add_task(self.store, "p", "fake", edit(path) + DONE, [scope], checks=checks)
        self.assertIsNone(dup)
        return tid

    def halves(self):
        a, b = self.add_with("src/a/a.py", "src/a", ["a"]), self.add_with("src/b/b.py", "src/b", ["b"])
        self.run_all()
        self.assertEqual((self.task(a)["status"], self.task(b)["status"]), ("COMPLETED", "COMPLETED"), self.task(a)["note"])
        return a, b

    def test_parallel_halves_integrate_one_by_one_and_promote_waits_for_every_check(self):
        a, b = self.halves()
        ran = {(r["task"], json.loads(r["data"])["name"]) for r in self.store.q("select task, data from events where kind = 'check'")}
        self.assertEqual(ran, {(a, "a"), (b, "b")})  # nothing ran on the wrong half
        integrate.integrate(self.rt, a)  # with a's own check only: the whole project could never pass with one half
        tip = integrate.integrate(self.rt, b)
        st = integrate.status(self.store, "p")
        self.assertEqual((st["can_promote"], st["verify_needed"], st["tasks"]), (False, True, [a, b]))
        self.assertIn("missing: a", st["reason"])
        with self.assertRaisesRegex(integrate.IntegrationError, "not every check has run"):
            integrate.promote(self.store, "p")
        self.assertEqual(integrate.verify(self.rt, "p"), tip)  # every check, on the merged commit
        st = integrate.status(self.store, "p")
        self.assertEqual((st["can_promote"], [c["name"] for c in st["checks"]]), (True, ["a", "b"]))
        self.assertEqual(integrate.promote(self.store, "p"), tip)

    def test_verify_fails_when_the_halves_do_not_fit_together_and_promote_stays_blocked(self):
        self.project({"a": "test -f src/a/a.py", "b": "test -f src/b/b.py", "fit": "test ! -e src/a/a.py -o ! -e src/b/b.py"})
        a, b = self.halves()
        integrate.integrate(self.rt, a)
        integrate.integrate(self.rt, b)
        with self.assertRaisesRegex(integrate.IntegrationError, "checks failed on the integration commit: fit"):
            integrate.verify(self.rt, "p")
        st = integrate.status(self.store, "p")
        self.assertEqual((st["can_promote"], st["verify_needed"]), (False, True))
        with self.assertRaises(integrate.IntegrationError):
            integrate.promote(self.store, "p")

    def test_a_task_without_a_check_subset_still_integrates_with_every_check(self):
        tid = self.add(edit("src/a/a.py") + DONE, scope=["src/a"])  # no subset: the whole project must pass
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "FAILED")  # its clone has no b.py: check b fails, as before

    def test_a_task_without_the_files_for_its_checks_still_fails(self):
        tid, _ = runtime.add_task(self.store, "p", "fake", edit("src/a/other.py") + DONE, ["src/a"], checks=["a"])
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "FAILED")  # its own check is not skipped

    def test_unknown_or_empty_check_lists_are_refused(self):
        for bad in (["nope"], []):
            with self.assertRaises(ValueError):
                runtime.add_task(self.store, "p", "fake", DONE, ["src"], checks=bad)

    def test_the_prompt_names_the_checks_that_verify_the_task(self):
        a = self.add_with("src/a/a.py", "src/a", ["a"])
        self.run_all()
        prompt = (self.tmp / "home" / "attempts" / f"{a}-1" / "prompt.txt").read_text()
        self.assertIn("Your result is verified by: a; the others belong to parallel work.", prompt)


class AskThenReport(AxonTest):
    def test_a_question_is_not_lost_when_the_agent_reports_after_asking(self):
        tid = self.add(step("mcp", tool="ask_user", args={"question": "which database?"})
                       + step("mcp", tool="report_result", args={"status": "done", "summary": "asked"}))
        self.run_all()
        self.assertEqual(self.task(tid)["status"], "WAITING_INPUT")  # not COMPLETED: the user still has to answer
        self.assertIn("which database?", self.task(tid)["note"])

    def test_a_long_choice_comes_back_whole(self):
        long = "one row per word: file, word_count, word, frequency; a file with no words gets one row with an empty word and frequency"
        tid = self.add(step("mcp", tool="ask_user", args={"question": "csv?", "options": [long, "x" * 900]}))
        self.run_all()
        options = runtime.ask_options(self.store, tid)
        self.assertEqual(options[0], long)  # was cut at 120 characters, so the agent could not tell what had been chosen
        self.assertEqual(len(options[1]), runtime.OPTION_MAX)


class PrepareAndReviewWithDependencies(AxonTest):
    """Projects with a `prepare` step (runs with network) and `require_review`: dependencies must not slip past either."""
    def setUp(self):
        super().setUp()
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text().replace("protected", "require_review = true\nprotected", 1)
                       + '[prepare]\ninstall = "true"\n[sandbox]\nprepare_inputs = ["pyproject.toml"]\n')

    def test_a_dependent_of_a_task_that_changed_dependency_files_waits_for_approval(self):
        a = self.add(edit("pyproject.toml", "[project]\n") + DONE, scope=["pyproject.toml"])
        b, _ = runtime.add_task(self.store, "p", "fake", edit("src/b/y.py") + DONE, ["src/b"], after=a)
        self.run_all()
        self.assertEqual(self.task(b)["status"], "WAITING_APPROVAL")
        self.assertIn("dependency files changed", self.task(b)["note"])
        self.assertTrue(runtime.approve(self.store, b))
        self.run_all()
        self.assertEqual(self.task(b)["status"], "COMPLETED")

    def test_a_dependent_of_plain_source_changes_just_runs(self):
        a = self.add(edit("src/a/x.py") + DONE, scope=["src/a"])
        b = self.add(edit("src/b/y.py") + DONE, scope=["src/b"])
        c, _ = runtime.add_task(self.store, "p", "fake", edit("src/c/z.py") + DONE, ["src/c"], after=a, needs=[b])
        self.run_all()
        self.assertEqual(self.task(c)["status"], "COMPLETED")
        self.assertEqual(len(self.store.q("select 1 from events where task = ? and kind = 'prepare'", c)), 1)

    def test_a_dependent_still_needs_its_own_review_to_integrate(self):
        a = self.add(edit("src/a/x.py") + DONE, scope=["src/a"])
        b, _ = runtime.add_task(self.store, "p", "fake", edit("src/b/y.py") + DONE, ["src/b"], after=a)
        self.run_all()
        with self.assertRaisesRegex(integrate.IntegrationError, "requires an approving review"):
            integrate.integrate(self.rt, b)

    def test_baseline_runs_prepare_first_and_names_what_is_red(self):
        self.assertEqual(integrate.baseline(self.rt, "p"), [])
        self.project({"ok": "true", "red": "false"})
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text() + '[prepare]\ninstall = "true"\n')
        self.assertEqual(integrate.baseline(self.rt, "p"), ["red"])

    def test_a_failing_prepare_is_the_baseline_problem(self):
        cfg = self.tmp / "cfg" / "projects" / "p.toml"
        cfg.write_text(cfg.read_text().replace('install = "true"', 'install = "false"'))
        self.assertEqual(integrate.baseline(self.rt, "p"), ["prepare install"])


class AgentEnvironment(AxonTest):
    def test_an_agent_cannot_leave_bytecode_in_its_result(self):
        tid = self.add(step("shell", cmd='python3 -c "import os; open(\'src/seen\', \'w\').write(os.environ[\'PYTHONDONTWRITEBYTECODE\'])"') + DONE)
        self.run_all()
        self.assertEqual(self.shown(f"{tid}-1", "src/seen"), "1")


class FileOperations(AxonTest):
    """D-040: Claude deletes and moves files through tools; any other agent asks first and a removal of its waits for the user."""
    def run_as(self, agent, *steps):
        with unittest.mock.patch.object(runtime, "CAN_MOVE", {agent}):
            tid = self.add("".join(steps), scope=["src"])
            self.run_all()
        return tid

    def test_the_agent_that_may_delete_and_move_files_can(self):
        tool = lambda name, **a: step("mcp", tool=name, args=a)
        tid = self.run_as("fake", tool("delete_file", path="src/a.py"), edit("src/new.py"), tool("move_file", **{"from": "src/new.py", "to": "src/sub/moved.py"}),
                          tool("move_file", **{"from": "docs/b.md", "to": "src/b.md"}), DONE)  # the last is outside its scope: refused
        self.assertEqual(self.task(tid)["status"], "COMPLETED")
        tree = self.git("ls-tree", "-r", "--name-only", f"refs/axon/attempts/{tid}-1").split()
        self.assertTrue({"src/sub/moved.py", "docs/b.md"} <= set(tree) and not {"src/a.py", "src/new.py", "src/b.md"} & set(tree), tree)

    def test_paths_outside_the_clone_and_directories_are_refused(self):
        t = {"agent": "claude", "kind": "", "scope": json.dumps(["src"])}
        for args in ({"path": "../x"}, {"path": "/etc/passwd"}, {"path": ".git/HEAD"}, {"path": "src"}, {"path": "src/none.py"}, {"path": "docs/b.md"}):
            ok, msg = self.rt._file_op(t, self.tmp / "proj", "delete_file", args)
            self.assertFalse(ok, args)
            self.assertTrue((self.tmp / "proj" / "src" / "a.py").exists())
        ok, msg = self.rt._file_op(t, self.tmp / "proj", "move_file", {"from": "src/a.py", "to": "src/a.py"})
        self.assertFalse(ok)  # the destination exists

    def test_another_agent_is_told_to_ask_and_its_removal_waits_for_the_user(self):
        tid = self.run_as("codex", step("mcp", tool="delete_file", args={"path": "src/a.py"}), step("shell", cmd="rm src/a.py"), DONE)
        task = self.task(tid)
        self.assertEqual(task["status"], "REVIEW")
        self.assertIn("removes: src/a.py", task["note"])
        ok, msg = self.rt._file_op({"agent": "codex", "kind": "", "scope": '["src"]'}, self.tmp / "proj", "delete_file", {"path": "src/a.py"})
        self.assertFalse(ok)
        self.assertIn("ask_peer", msg)
