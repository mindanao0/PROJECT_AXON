"""Brainstorm (D-035): two agents plan together, nothing runs until the user creates the tasks. The fake agent plays both."""

import contextlib
import io
import json
from pathlib import Path
import threading
import time
from unittest import mock

from axon import brainstorm, cli, runtime
from axon.core import ControlError
from test_axon import AxonTest, step
from test_bridge import BridgeTest


def say(phase, text, status="done", **kw):
    return step("mcp", tool="report_result", args={"status": status, "summary": text}, phase=phase, **kw)


def task(id, after=None, **kw):
    return {"id": id, "title": f"task {id}", "agent": "fake", "scope": ["src/" + id], "after": after, "by": "both",
            "objective": f"do {id}", "context": "the user wants it small", "files": ["src/" + id + ".py"], "steps": ["edit", "test"],
            "constraints": ["do not touch tests/"], "acceptance": ["python -m unittest exits 0"], "report": "the test output"} | kw


def plan(**extra):
    p = {"goal": "g", "summary": "s", "risks": [], "unknowns": [], "disagreements": [], "tasks": [task("a"), task("b", after="a", by="fake")]}
    return json.dumps(p | extra)


def phased(**extra):
    ph = lambda i: {"id": f"p{i}", "title": f"phase {i}", "objective": f"o{i}", "done_when": ["it works"], "tasks": []}
    return json.dumps({"goal": "g", "summary": "s", "design": "d", "risks": [], "unknowns": [], "disagreements": [], "phases": [ph(1), ph(2)]} | extra)


HAPPY = (say("clarify", "clear") + say("draft", plan()) + say("compare", "they agree") + say("merge", plan()) + say("check", "fine"))


class Brainstorm(AxonTest):
    def start(self, goal, **kw):
        bid = brainstorm.start(self.store, "p", goal, lead="fake", other="fake", **kw)
        self.run_all()
        return bid

    def state(self, bid):
        b = self.store.one("select * from brainstorms where id = ?", bid)
        return b["status"], b["phase"], json.loads(b["data"])

    def prompts(self, bid, phase):
        return [(runtime.data_dir() / "attempts" / f"{t['id']}-1" / "prompt.txt").read_text()
                for t in self.store.q("select id from tasks where kind = 'plan' and spec like ? order by id", f"# Brainstorm {bid} {phase} %")]

    def test_two_agents_plan_then_the_user_creates_the_tasks(self):
        bid = self.start(HAPPY)
        status, phase, d = self.state(bid)
        self.assertEqual((status, phase), ("READY", "ready"))
        self.assertEqual(d["objections"], "")
        self.assertFalse(self.store.q("select id from tasks where kind = ''"))  # nothing was built or queued
        for phase in ("clarify", "draft", "compare", "merge", "check"):
            for p in self.prompts(bid, phase):
                self.assertIn("call the report_result tool", p.split("--- task ---")[0])  # an interactive Claude must not just print its answer
                self.assertIn("in English", p)
        for p in self.prompts(bid, "draft"):
            self.assertNotIn("--- your plan ---", p)  # they draft alone
        for p in self.prompts(bid, "compare"):
            self.assertIn("--- your plan ---", p)
        ids = brainstorm.create_tasks(self.store, bid)
        t1, t2 = (self.task(ids[k]) for k in ("a", "b"))
        self.assertEqual((t1["after"], t2["after"], json.loads(t2["scope"])), (None, t1["id"], ["src/b"]))
        shown = brainstorm.describe(self.store, bid)["plan"]["phases"][0]["tasks"]
        self.assertEqual(t1["spec"], shown[0]["brief"])  # what the user was shown is what the agent gets
        self.assertEqual(brainstorm.create_tasks(self.store, bid), ids)  # twice is harmless
        self.assertEqual(self.state(bid)[0], "DONE")
        self.assertIn("## Plan", t1["spec"])  # each agent knows where its task sits in the whole
        files = brainstorm.describe(self.store, bid)["files"]  # PLAN.md for the user, plan.json for an agent: one source
        ai = json.loads(Path(files["ai"]).read_text())
        self.assertEqual([t["id"] for t in ai["phases"][0]["tasks"]], [t["id"] for t in d["plan"]["tasks"]])
        for t in d["plan"]["tasks"]:
            self.assertIn(t["title"], Path(files["human"]).read_text())

    def test_a_big_plan_is_broken_into_tasks_one_phase_at_a_time(self):
        first = say("expand", json.dumps({"tasks": [task("a"), task("b", after="a")]}), has="(none yet)")
        second = say("expand", json.dumps({"tasks": [task("c")]}), lacks="(none yet)")
        big = HAPPY.replace(say("draft", plan()), say("draft", phased())).replace(say("merge", plan()), say("merge", phased()))
        bid = self.start(big + first + second)
        self.assertEqual(self.state(bid)[0], "READY")
        with self.assertRaisesRegex(ValueError, "break it down first"):
            brainstorm.create_tasks(self.store, bid)
        with self.assertRaisesRegex(ValueError, "finish the phases before"):
            brainstorm.expand(self.store, bid, "p2")
        brainstorm.expand(self.store, bid)
        self.assertEqual(self.state(bid)[0], "ACTIVE")
        self.run_all()
        status, _, d = self.state(bid)
        self.assertEqual((status, [len(p["tasks"]) for p in d["plan"]["phases"]]), ("READY", [2, 0]))
        self.assertIn("phase 1", Path(brainstorm.describe(self.store, bid)["files"]["human"]).read_text())
        ids = brainstorm.create_tasks(self.store, bid)
        self.assertEqual(sorted(ids), ["a", "b"])
        self.assertEqual(self.state(bid)[0], "READY")  # phase 2 is still to come
        with self.assertRaisesRegex(ValueError, "finish the phases before"):
            brainstorm.expand(self.store, bid)  # phase 1 is not done yet
        for tid in ids.values():
            self.store.move(tid, "COMPLETED", ("QUEUED",), note="built it")
        brainstorm.expand(self.store, bid)
        self.run_all()
        self.assertIn("built it", self.prompts(bid, "expand")[-1])  # the next phase is planned from what the last one did
        brainstorm.create_tasks(self.store, bid)
        self.assertEqual(self.state(bid)[0], "DONE")

    def test_a_task_may_wait_for_several_and_a_phase_builds_on_the_one_before(self):
        first = say("expand", json.dumps({"tasks": [task("a"), task("b"), task("c", after=["a", "b"])]}), has="(none yet)")
        second = say("expand", json.dumps({"tasks": [task("d")]}), lacks="(none yet)")
        big = HAPPY.replace(say("draft", plan()), say("draft", phased())).replace(say("merge", plan()), say("merge", phased()))
        bid = self.start(big + first + second)
        brainstorm.expand(self.store, bid)
        self.run_all()
        ids = brainstorm.create_tasks(self.store, bid)
        row = lambda k: self.store.one("select after, needs from tasks where id = ?", ids[k])
        self.assertEqual((row("a")["after"], row("c")["after"], json.loads(row("c")["needs"])), (None, ids["a"], [ids["b"]]))
        self.assertIn("starts after a, b", brainstorm.brief(task("c", after=["a", "b"]), {"phases": [{"id": "p1", "title": "t", "tasks": [task("a"), task("b"), task("c", after=["a", "b"])]}]}))
        for tid in ids.values():
            self.store.move(tid, "COMPLETED", ("QUEUED",), note="built it")
        brainstorm.expand(self.store, bid)
        self.run_all()
        ids = brainstorm.create_tasks(self.store, bid)
        d = self.store.one("select after, needs from tasks where id = ?", ids["d"])
        self.assertEqual((d["after"], sorted(json.loads(d["needs"]))), (ids["a"], sorted([ids["b"], ids["c"]])))  # the whole phase before it
        with self.assertRaisesRegex(ValueError, "list of task ids"):
            brainstorm.parse_plan(plan(tasks=[task("a", after=3)]))
        with self.assertRaisesRegex(ValueError, "earlier tasks"):
            brainstorm.parse_plan(plan(tasks=[task("a", after=["zzz"])]))

    def test_a_started_phase_makes_again_only_the_tasks_that_failed_or_were_stopped(self):
        bid = self.start(HAPPY)
        ids = brainstorm.create_tasks(self.store, bid)
        with self.assertRaisesRegex(ValueError, "already started"):
            brainstorm.create_tasks(self.store, bid, "p1")  # nothing failed: nothing to do
        self.store.move(ids["a"], "COMPLETED", ("QUEUED",), note="done")
        self.store.move(ids["b"], "CANCELLED", ("QUEUED",), note="stopped")
        again = brainstorm.create_tasks(self.store, bid, "p1")
        self.assertEqual(again["a"], ids["a"])  # finished work is kept
        self.assertNotEqual(again["b"], ids["b"])
        self.assertEqual(brainstorm.describe(self.store, bid)["plan"]["phases"][0]["failed"], 0)
        self.assertEqual(self.store.one("select after from tasks where id = ?", again["b"])["after"], ids["a"])
        self.assertEqual(brainstorm.baseline_error(self.rt, bid), "")  # a project without checks cannot start red
        with mock.patch("axon.integrate.baseline", return_value=["unit"]):
            self.assertIn("(unit)", brainstorm.baseline_error(self.rt, bid))
        with self.assertRaisesRegex(ValueError, '"checks" must be a list'):
            brainstorm.parse_plan(plan(tasks=[task("a", checks="unit")]))

    def test_retrying_a_phase_also_makes_again_the_waiting_tasks_that_follow_a_dead_one(self):
        bid = self.start(HAPPY)
        ids = brainstorm.create_tasks(self.store, bid)
        self.store.move(ids["a"], "FAILED", ("QUEUED",), note="could not")  # b is still queued, waiting for a
        again = brainstorm.create_tasks(self.store, bid, "p1")
        self.assertEqual(self.store.one("select status from tasks where id = ?", ids["b"])["status"], "CANCELLED")
        self.assertEqual(self.store.one("select after from tasks where id = ?", again["b"])["after"], again["a"])
        self.assertEqual(self.store.one("select status from tasks where id = ?", again["b"])["status"], "QUEUED")

    def test_the_checker_is_told_an_empty_phase_is_deliberate(self):
        self.assertIn("do not object that it has no tasks", brainstorm.STEPS["check"])

    def test_a_plan_over_the_cap_is_refused_and_a_bad_expansion_leaves_the_plan_alone(self):
        many = {"phases": [{"id": "p1", "title": "t", "objective": "o", "tasks": [task(f"t{i}") for i in range(brainstorm.PHASE_CAP + 1)]}]}
        with self.assertRaisesRegex(ValueError, "at most"):
            brainstorm.parse_plan(plan(**many))
        big = HAPPY.replace(say("draft", plan()), say("draft", phased())).replace(say("merge", plan()), say("merge", phased()))
        bid = self.start(big + say("expand", "no json", status="done"))
        brainstorm.expand(self.store, bid)
        self.run_all()
        status, _, d = self.state(bid)
        self.assertEqual((status, d["expand_tries"]), ("READY", brainstorm.MERGE_TRIES))
        self.assertIn("could not be broken down", d["expand_error"])
        self.assertEqual([len(p["tasks"]) for p in d["plan"]["phases"]], [0, 0])

    def test_both_may_ask_and_the_answers_reach_every_later_prompt(self):
        ask = step("mcp", tool="ask_user", args={"question": "which database?"}, phase="clarify", role="lead", lacks="--- the user's answers so far ---")
        bid = self.start(ask + say("clarify", "clear", has="--- the user's answers so far ---") + say("clarify", "clear", role="other") + HAPPY[HAPPY.index('[[step]]\ndo = "mcp"\ntool = "report_result"\nargs = {status = "done", summary = "{\\"goal'):])
        asking = self.store.one("select id from tasks where kind = 'plan' and status = 'WAITING_INPUT'")
        self.assertEqual(self.state(bid)[:2], ("ACTIVE", "clarify"))
        self.assertTrue(runtime.answer(self.store, asking["id"], "sqlite"))
        self.run_all()
        status, _, d = self.state(bid)
        self.assertEqual((status, d["clarify_round"], d["qa"][0]["q"], d["qa"][0]["a"]), ("READY", 1, "which database?", "sqlite"))
        for phase in ("clarify", "draft", "compare", "merge", "check"):
            self.assertIn("A: sqlite", self.prompts(bid, phase)[-1])

    def test_a_plan_with_unknowns_is_not_ready(self):
        bad = say("merge", plan(unknowns=["which db"]), lacks="rejected")
        bid = self.start(HAPPY.replace(say("merge", plan()), bad + say("merge", plan(), has="rejected")))
        status, _, d = self.state(bid)
        self.assertEqual((status, d["merge_tries"]), ("READY", 1))
        self.assertEqual(d["plan"]["unknowns"], [])
        self.assertIn("unknowns", self.prompts(bid, "merge")[-1])  # the second merge was told why

    def test_a_merge_that_never_gets_valid_fails_the_brainstorm(self):
        bid = self.start(HAPPY.replace(say("merge", plan()), say("merge", "no json here")))
        status, _, d = self.state(bid)
        self.assertEqual(status, "FAILED")
        self.assertIn("no usable plan", d["why"])

    def test_an_objection_gets_one_more_merge_then_the_user_decides(self):
        v2 = plan(summary="v2")
        script = (say("clarify", "clear") + say("draft", plan()) + say("compare", "ok") + say("merge", plan(), lacks="objections from")
                  + say("merge", v2, has="objections from") + say("check", "needs tests", status="failed", lacks="v2")
                  + say("check", "still not enough", status="failed", has="v2"))
        bid = self.start(script)
        status, _, d = self.state(bid)
        self.assertEqual((status, d["round"], d["plan"]["summary"], d["objections"]), ("READY", 1, "v2", "still not enough"))

    def test_a_failed_agent_fails_the_brainstorm(self):
        bid = self.start(HAPPY.replace(say("draft", plan()), step("crash", code=3, phase="draft", role="other") + say("draft", plan())))
        status, _, d = self.state(bid)
        self.assertEqual(status, "FAILED")
        self.assertIn("ended without an answer", d["why"])

    def test_a_task_picked_up_before_start_has_saved_the_brainstorm_still_works(self):
        # `start` runs in the GUI or CLI while the runner, elsewhere, may start a task the moment it exists.
        bid = brainstorm.start(self.store, "p", HAPPY, lead="fake", other="fake")
        b, d = brainstorm._load(self.store, bid)
        saved, d["tasks"] = dict(d["tasks"]), {}
        brainstorm._save(self.store, bid, d)  # the window: tasks exist, the brainstorm does not list them yet
        task = self.store.one("select * from tasks where id = ?", saved["other"])
        self.assertIn("Brainstorm role: other", brainstorm.prompt(self.rt, task))
        self.assertFalse(brainstorm.advance(self.rt))  # nothing to advance yet: it must not skip to the next phase
        self.assertEqual(self.state(bid)[1], "clarify")
        d["tasks"] = saved
        brainstorm._save(self.store, bid, d)
        self.run_all()
        self.assertEqual(self.state(bid)[0], "READY")

    def test_stopping_a_brainstorm_stops_its_tasks(self):
        bid = brainstorm.start(self.store, "p", step("hang"), lead="fake", other="fake")
        self.rt.tick()
        threading.Thread(target=lambda: time.sleep(1.5) or brainstorm.cancel(self.store, bid)).start()
        self.run_all()
        self.assertEqual(self.state(bid)[0], "CANCELLED")
        self.assertFalse(self.store.q("select id from tasks where kind = 'plan' and status not in ('CANCELLED', 'FAILED')"))


class Settings(AxonTest):
    """model/effort: this brainstorm's own choice, then merge_effort (merge step), then [brainstorm], else the [agents] setting."""

    def setUp(self):
        super().setUp()
        cfg = self.tmp / "cfg" / "config.toml"
        cfg.write_text(cfg.read_text() + '[brainstorm]\nclaude_effort = "low"\ncodex_model = "gpt-x"\nmerge_effort = "high"\n')

    def test_order_of_choice(self):
        d = {"agents": {"lead": "claude", "other": "codex"}, "opts": {}}
        me = lambda role, phase, opts=None: brainstorm._model_effort(d | {"opts": opts or {}}, role, phase)
        self.assertEqual(me("lead", "draft"), (None, "low"))
        self.assertEqual(me("lead", "merge"), (None, "high"))
        self.assertEqual(me("other", "draft"), ("gpt-x", None))
        self.assertEqual(me("lead", "merge", {"lead": {"effort": "max", "model": "opus"}}), ("opus", "max"))
        self.assertEqual(me("lead", "gate"), (None, None))  # the question merge falls back to the light values, here unset
        self.assertEqual(me("lead", "gate", {"lead": {"light_model": "sonnet", "gate_model": "haiku"}}), ("haiku", None))
        self.assertEqual(me("lead", "clarify", {"lead": {"light_model": "sonnet", "gate_model": "haiku"}}), ("sonnet", None))  # gate_* is for the merge only
        self.assertEqual(me("lead", "clarify"), (None, None))  # the light steps have their own settings, unset here
        self.assertEqual(me("other", "check", {"other": {"light_model": "sol", "light_effort": "medium", "model": "astra"}}), ("sol", "medium"))

    def test_a_setting_the_agent_would_reject_fails_before_anything_starts(self):
        with self.assertRaisesRegex(ValueError, "effort for claude"):
            brainstorm.start(self.store, "p", "goal", opts={"lead": {"effort": "ultra"}})
        self.assertFalse(self.store.q("select id from brainstorms"))
        self.assertFalse(self.store.q("select id from tasks"))


ASK = step("mcp", tool="ask_user", args={"question": "which database?", "options": ["sqlite", "postgres"]}, phase="clarify", role="lead",
           lacks="--- the user's answers so far ---")
ASKING = ASK + say("clarify", "clear", role="other") + say("clarify", "clear", has="--- the user's answers so far ---") + HAPPY[HAPPY.index(say("draft", plan())):]


class Screens(BridgeTest):
    def test_the_gui_starts_answers_and_creates_the_tasks(self):
        r = self.b.command({"action": "brainstorm_start", "project_id": "p", "goal": ASKING, "lead": "fake", "other": "fake"})
        snap = self.pump(lambda s: s["brainstorms"] and s["brainstorms"][0]["questions"])
        (q,) = snap["brainstorms"][0]["questions"]
        self.assertEqual((q["question"], q["options"]), ("which database?", ["sqlite", "postgres"]))
        self.b.command({"action": "answer", "task_id": q["task_id"], "attempt_id": q["attempt_id"], "pending_id": q["pending_id"], "text": "sqlite"})
        snap = self.pump(lambda s: s["brainstorms"][0]["status"] == "READY")
        self.assertEqual(snap["brainstorms"][0]["qa"][0]["a"], "sqlite")
        with mock.patch("axon.integrate.baseline", return_value=["unit"]):  # red before any task: ask first, nothing is made
            warn = self.b.command({"action": "brainstorm_create_tasks", "brainstorm_id": r["brainstorm_id"]})
            self.assertIn("(unit)", warn["warning"])
            self.assertEqual(len([t for t in self.b.snapshot()["tasks"] if t["kind"] == "task"]), 0)
            out = self.b.command({"action": "brainstorm_create_tasks", "brainstorm_id": r["brainstorm_id"], "force": True})
        self.assertEqual(set(out["task_ids"]), {"a", "b"})
        self.assertEqual(len([t for t in self.b.snapshot()["tasks"] if t["kind"] == "task"]), 2)
        with self.assertRaises(ControlError):
            self.b.command({"action": "brainstorm_start", "project_id": "nope", "goal": "x"})

    def test_the_gui_can_stop_it(self):
        r = self.b.command({"action": "brainstorm_start", "project_id": "p", "goal": step("hang"), "lead": "fake", "other": "fake"})
        self.b.tick()
        self.b.command({"action": "brainstorm_stop", "brainstorm_id": r["brainstorm_id"]})
        self.assertEqual(self.b.snapshot()["brainstorms"][0]["status"], "CANCELLED")


class Cli(AxonTest):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def test_start_look_and_approve(self):
        bid = self.run_cli("brainstorm", HAPPY, "-p", "p", "--lead", "fake", "--other", "fake").strip()
        self.run_all()
        shown = self.run_cli("brainstorm", bid)
        self.assertIn("READY", shown)
        self.assertIn(f"axon brainstorm {bid} --approve", shown)
        self.assertIn("b -> task", self.run_cli("brainstorm", bid, "--approve"))
        self.assertIn("DONE", self.run_cli("brainstorm"))


class Brief(AxonTest):
    def test_a_fresh_agent_gets_a_complete_brief(self):
        text = brainstorm.brief(task("a"))
        for heading in ("# task a", "## Objective", "## Context", "## Files", "## Steps\n1. edit\n2. test", "## Constraints", "## Acceptance", "## Report"):
            self.assertIn(heading, text)
        self.assertNotIn("## Context", brainstorm.brief(task("a", context="")))  # empty optional parts leave no empty heading

    def test_a_plan_without_a_way_to_check_the_work_is_refused(self):
        for bad in ({"acceptance": []}, {"steps": []}, {"objective": " "}, {"files": "src/a.py"}, {"constraints": [3]}):
            with self.assertRaises(ValueError, msg=bad):
                brainstorm.parse_plan(plan(tasks=[task("a", **bad)]))
        with self.assertRaisesRegex(ValueError, "acceptance"):
            brainstorm.parse_plan(plan(tasks=[{k: v for k, v in task("a").items() if k != "acceptance"}]))

    def test_a_plan_stored_before_the_brief_fields_still_shows_and_creates(self):
        legacy = {"id": "t1", "title": "old", "agent": "fake", "scope": ["src"], "spec": "just do it", "after": None}
        self.assertIn("just do it", brainstorm.brief(legacy))


class Questions(BridgeTest):
    """ask_user with several questions: asked together, each with its own choices, answered together."""

    def test_several_questions_in_one_ask(self):
        qs = [{"question": "Read from stdin or a file?", "options": ["stdin", "file"]}, {"question": "Output format?"}]
        tid = self.create(step("mcp", tool="ask_user", args={"questions": qs}))
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "WAITING_INPUT")
        pending = self.task(snap, tid)["pending"]
        self.assertEqual(pending["message"], "1) Read from stdin or a file?\n2) Output format?")
        self.assertEqual(pending["questions"], [{"question": "Read from stdin or a file?", "options": ["stdin", "file"]},
                                                {"question": "Output format?", "options": []}])
        self.assertEqual(pending["options"], [])  # not a flat list of choices that belong to different questions
        self.cmd(tid, "answer", pending_id=pending["id"], text="1) stdin\n2) plain text")
        self.assertIn("A: 1) stdin\n2) plain text", self.store.one("select context from tasks where id = ?", int(tid))["context"])

    def test_one_plain_question_still_works_and_empty_questions_are_not_a_question(self):
        tid = self.create(step("mcp", tool="ask_user", args={"question": "which?", "options": ["a", "b"]}))
        snap = self.pump(lambda s: self.task(s, tid)["state"] == "WAITING_INPUT")
        pending = self.task(snap, tid)["pending"]
        self.assertEqual((pending["message"], pending["options"], pending["questions"]), ("which?", ["a", "b"], []))
        self.assertEqual(runtime.ask_questions(self.store, int(tid)), [])


# --- the question gate: questions both agents ask at once are merged, so the user answers each thing once ---

NOTES = "--- the user's answers so far ---"  # in a prompt only once there are answers: a resumed task and a new round both have it
TAIL = HAPPY[HAPPY.index(say("draft", plan())):]


def asks(role, *questions):
    return step("mcp", tool="ask_user", args={"questions": [{"question": q, "options": ["a", "b"]} for q in questions]},
                phase="clarify", role=role, lacks=NOTES)


def merged(*groups):
    return json.dumps({"questions": [{"question": q, "options": ["a", "b"], "covers": covers} for q, covers in groups]})


BOTH_ASK = (asks("lead", "Input from stdin or a file?", "Output format?") + asks("other", "Where does the text come from?")
            + say("clarify", "clear", has=NOTES)
            + say("gate", merged(("Where does the text come from: stdin or a file?", ["lead#1", "other#1"]), ("Output format?", ["lead#2"])))
            + TAIL)


class Gate(AxonTest):
    def start(self, script, **kw):
        bid = brainstorm.start(self.store, "p", script, lead="fake", other="fake", **kw)
        self.run_all()
        return bid

    def shown(self, bid):
        return brainstorm.describe(self.store, bid)

    def test_two_agents_asking_at_once_get_one_merged_form(self):
        bid = self.start(BOTH_ASK)
        b = self.shown(bid)
        (form,) = b["questions"]  # not the agents' three separate questions
        self.assertTrue(form["gate"])
        self.assertEqual([q["question"] for q in form["questions"]], ["Where does the text come from: stdin or a file?", "Output format?"])
        self.assertEqual(len(form["questions"][0]["from"]), 2)  # the user can see both original wordings
        self.assertEqual(len(form["questions"][1]["from"]), 1)
        self.assertFalse(b["collecting"])
        # answered once; every agent gets what it asked
        brainstorm.answer_gate(self.store, bid, ["a file", "plain text"])
        self.run_all()
        r = self.store.one("select * from brainstorms where id = ?", bid)
        status, d = r["status"], json.loads(r["data"])
        self.assertEqual(status, "READY")
        self.assertEqual([(x["q"], x["a"]) for x in d["qa"]],
                         [("Where does the text come from: stdin or a file?", "a file"), ("Output format?", "plain text")])  # recorded once
        ctx = {t["agent"] + str(t["id"]): t["context"] for t in self.store.q("select id, agent, context from tasks where kind = 'plan' and spec like '%clarify%'")}
        lead_ctx = next(c for c in ctx.values() if "Output format?" in c and "Input from stdin" in c)
        self.assertIn("A: a file", lead_ctx)
        other_ctx = next(c for c in ctx.values() if "Where does the text come" in c and "Input from stdin" not in c)
        self.assertNotIn("Output format?\nA: plain text", other_ctx.split("A (answers merged")[-1])  # it did not ask that

    def test_one_agent_alone_asks_directly(self):
        script = asks("lead", "Which?") + say("clarify", "clear", role="other") + say("clarify", "clear", has=NOTES) + TAIL
        bid = self.start(script)
        (q,) = self.shown(bid)["questions"]
        self.assertNotIn("gate", q)
        self.assertFalse(self.store.q("select id from tasks where spec like '# Brainstorm % gate lead %'"))  # no merge was run

    def test_a_merge_that_loses_a_question_falls_back_to_the_agents_own(self):
        script = (asks("lead", "One?") + asks("other", "Two?")
                  + say("gate", merged(("One?", ["lead#1"]))) + TAIL)  # other#1 is missing, both times
        bid = self.start(script)
        b = self.shown(bid)
        self.assertEqual(sorted(x["questions"][0]["question"] for x in b["questions"]), ["One?", "Two?"])  # each agent's own
        self.assertNotIn("gate", b["questions"][0])
        self.assertEqual(len(self.store.q("select id from tasks where spec like '# Brainstorm % gate lead %'")), 2)  # tried, told what was wrong, tried again

    def test_the_first_asker_waits_for_the_other_but_only_so_long(self):
        script = asks("lead", "Which?") + step("sleep", s=8, phase="clarify", role="other") + say("clarify", "clear", role="other") + TAIL
        with mock.patch.object(brainstorm, "GATE_WAIT", 2):
            bid = brainstorm.start(self.store, "p", script, lead="fake", other="fake")
            self.wait(lambda: (self.rt.tick(), self.shown(bid)["collecting"])[1])
            self.assertEqual(self.shown(bid)["questions"], [])  # held: its questions are not shown alone yet
            self.wait(lambda: (self.rt.tick(), self.shown(bid)["questions"])[1], timeout=15)
            self.assertEqual(self.shown(bid)["questions"][0]["question"], "1) Which?")  # past the wait: shown on their own
            brainstorm.cancel(self.store, bid)
            for th in self.rt.threads:
                th.join(30)

    def test_answers_must_cover_every_merged_question(self):
        bid = self.start(BOTH_ASK)
        for bad in ([], ["only one"], ["a", " "], "text"):
            with self.assertRaises(ValueError, msg=bad):
                brainstorm.answer_gate(self.store, bid, bad)
        brainstorm.answer_gate(self.store, bid, ["x", "y"])
        with self.assertRaises(ValueError):  # nothing left to answer
            brainstorm.answer_gate(self.store, bid, ["x", "y"])

    def test_parse_gate_rejects_a_dropped_question(self):
        ids = {"lead#1": {}, "other#1": {}}
        brainstorm.parse_gate(merged(("q", ["lead#1", "other#1"])), ids)
        for bad in (merged(("q", ["lead#1"])), merged(("q", ["nobody#9", "lead#1", "other#1"])), "no json", '{"questions": []}'):
            with self.assertRaises(ValueError, msg=bad):
                brainstorm.parse_gate(bad, ids)


class GateScreens(BridgeTest):
    def test_the_agents_own_tasks_do_not_ask_a_second_time(self):
        r = self.b.command({"action": "brainstorm_start", "project_id": "p", "goal": BOTH_ASK, "lead": "fake", "other": "fake"})
        snap = self.pump(lambda s: s["brainstorms"] and any(q.get("gate") for q in s["brainstorms"][0]["questions"]))
        held = [t for t in snap["tasks"] if t["state"] == "WAITING_INPUT"]
        self.assertEqual(len(held), 2)  # both agents wait for an answer ...
        for t in held:  # ... but the user is not asked through them
            self.assertIsNone(t["pending"])
            self.assertEqual(t["held_by"], r["brainstorm_id"])
            self.assertIn(f"Brainstorm #{r['brainstorm_id']}", t["activity"])  # the card itself says where to answer
            with self.assertRaisesRegex(ControlError, "Brainstorm page"):
                self.b.command({"action": "answer", "task_id": t["id"], "attempt_id": t["attempt_id"],
                                "pending_id": f"{t['id']}:{t['attempt_id']}:WAITING_INPUT", "text": "x"})
            with self.assertRaises(ValueError):
                runtime.answer(self.store, int(t["id"]), "x")
        self.b.command({"action": "brainstorm_answer", "brainstorm_id": r["brainstorm_id"], "answers": ["a file", "plain text"]})
        self.assertFalse(any(brainstorm.held(self.store, int(t["id"])) for t in held))

    def test_the_gui_answers_the_merged_form(self):
        r = self.b.command({"action": "brainstorm_start", "project_id": "p", "goal": BOTH_ASK, "lead": "fake", "other": "fake"})
        snap = self.pump(lambda s: s["brainstorms"] and any(q.get("gate") for q in s["brainstorms"][0]["questions"]))
        self.b.command({"action": "brainstorm_answer", "brainstorm_id": r["brainstorm_id"], "answers": ["a file", "plain text"]})
        self.pump(lambda s: s["brainstorms"][0]["status"] == "READY")
        with self.assertRaises(ControlError):
            self.b.command({"action": "brainstorm_answer", "brainstorm_id": r["brainstorm_id"], "answers": ["x", "y"]})
