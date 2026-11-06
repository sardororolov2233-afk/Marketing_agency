import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.workflow import Actor, Content, Forbidden, WorkflowError


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.project = uuid4()
        self.owner = Actor(uuid4(), self.project, "owner")
        self.editor = Actor(uuid4(), self.project, "editor")
        self.now = datetime.now(timezone.utc)
        self.content = Content(self.project, "telegram")

    def approve(self):
        version = self.content.revise(self.editor, "Hello")
        self.content.submit(self.editor)
        self.content.decide(self.owner, version.id, version.checksum, True, self.now)
        return version

    def test_revision_invalidates_approval_and_old_job(self):
        version = self.approve()
        job = self.content.schedule(self.owner, version.id, self.now, self.now)
        updated = self.content.revise(self.editor, "Changed")
        self.assertEqual(self.content.state, "draft")
        with self.assertRaises(WorkflowError):
            job.begin(self.content, self.now)
        with self.assertRaises(WorkflowError):
            self.content.schedule(self.owner, updated.id, self.now, self.now)
        self.content.submit(self.editor)
        with self.assertRaises(WorkflowError):
            self.content.decide(self.owner, version.id, version.checksum, True, self.now)

    def test_other_project_and_editor_cannot_approve(self):
        version = self.content.revise(self.editor, "Hello")
        self.content.submit(self.editor)
        for actor in (self.editor, Actor(uuid4(), uuid4(), "owner")):
            with self.assertRaises(Forbidden):
                self.content.decide(actor, version.id, version.checksum, True, self.now)
        self.assertEqual(self.content.state, "awaiting_approval")

    def test_uncertain_publish_cannot_be_automatically_retried(self):
        version = self.approve()
        job = self.content.schedule(self.owner, version.id, self.now, self.now)
        job.begin(self.content, self.now)
        job.uncertain(self.content)
        with self.assertRaises(WorkflowError):
            job.begin(self.content, self.now)
        with self.assertRaises(WorkflowError):
            self.content.revise(self.editor, "New")

    def test_due_and_receipt_required(self):
        version = self.approve()
        job = self.content.schedule(self.owner, version.id, self.now + timedelta(minutes=1), self.now)
        with self.assertRaises(WorkflowError):
            job.begin(self.content, self.now)
        job.begin(self.content, self.now + timedelta(minutes=1))
        with self.assertRaises(WorkflowError):
            job.complete(self.content, "")
        job.complete(self.content, "telegram:123")
        self.assertEqual(self.content.state, "published")
        self.assertEqual(job.remote_id, "telegram:123")


if __name__ == "__main__":
    unittest.main()
