import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import riya_server

class ConversationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tasks = [{
            'task_id': 'meeting-1', 'title': 'One-on-one meeting',
            'duration_minutes': 60, 'scheduled': False
        }]

    def test_list_them_request_is_detected(self):
        self.assertTrue(riya_server.is_task_list_request("list them"))
        self.assertTrue(riya_server.is_task_list_request("show me my tasks"))

    def test_task_list_is_formatted_in_chat(self):
        tasks = [
            {"title": "Verilog assignment", "priority": "High"},
            {"title": "FPGA practice", "priority": "High"},
            {"title": "Internship report"},
        ]
        reply = riya_server.format_task_list_reply(tasks)
        self.assertIn("Here are your 3 tasks", reply)
        self.assertIn("1. Verilog assignment — High priority", reply)
        self.assertIn("2. FPGA practice — High priority", reply)
        self.assertIn("3. Internship report", reply)

    def test_schedule_proposal_is_also_shown_in_chat(self):
        tasks = [{"title": "Verilog assignment"}, {"title": "FPGA practice"}]
        preview = {"entries": [
            {"title": "Verilog assignment", "date": "2026-11-13", "start_time": "09:00", "end_time": "10:00"},
            {"title": "FPGA practice", "date": "2026-11-14", "start_time": "10:00", "end_time": "11:00"},
        ]}
        reply = riya_server.format_task_list_reply(tasks, preview)
        self.assertIn("Proposed time slots", reply)
        self.assertIn("Verilog assignment — 2026-11-13, 09:00–10:00", reply)
        self.assertIn("Nothing is saved until you approve it", reply)

    def test_unrelated_followup_does_not_reactivate_old_schedule(self):
        messages = [
            {'role':'user','content':'Schedule my one-on-one meeting tomorrow between 3pm and 4pm'},
            {'role':'assistant','content':'I have laid out a proposal. Nothing is saved until you approve it.'},
            {'role':'user','content':'what else?'},
        ]
        self.assertIsNone(riya_server.build_context_schedule(messages, self.tasks, '2026-11-11'))

    def test_new_task_message_does_not_reactivate_old_schedule(self):
        messages = [
            {'role':'user','content':'Schedule my one-on-one meeting tomorrow between 3pm and 4pm'},
            {'role':'assistant','content':'I have laid out a proposal. Nothing is saved until you approve it.'},
            {'role':'user','content':'i have to complete my verilog assignments'},
        ]
        self.assertIsNone(riya_server.build_context_schedule(messages, self.tasks, '2026-11-11'))

    def test_relative_fragment_does_not_reactivate_old_schedule(self):
        messages = [
            {'role':'user','content':'Schedule my one-on-one meeting tomorrow between 3pm and 4pm'},
            {'role':'assistant','content':'I have laid out a proposal. Nothing is saved until you approve it.'},
            {'role':'user','content':'two days after'},
        ]
        self.assertIsNone(riya_server.build_context_schedule(messages, self.tasks, '2026-11-11'))

    def test_current_explicit_schedule_instruction_still_builds_preview(self):
        messages = [{'role':'user','content':'Schedule my one-on-one meeting tomorrow between 3pm and 4pm'}]
        result = riya_server.build_context_schedule(messages, self.tasks, '2026-11-11')
        self.assertIsNotNone(result)
        self.assertEqual(result['entries'][0]['date'], '2026-11-12')
        self.assertEqual(result['entries'][0]['start_time'], '15:00')
        self.assertEqual(result['entries'][0]['end_time'], '16:00')

    def test_explicit_approval_can_reuse_immediately_presented_proposal(self):
        messages = [
            {'role':'user','content':'Schedule my one-on-one meeting tomorrow between 3pm and 4pm'},
            {'role':'assistant','content':'Here is the schedule proposal. Nothing is saved until you approve it.'},
            {'role':'user','content':'approve it'},
        ]
        result = riya_server.build_context_schedule(messages, self.tasks, '2026-11-11')
        self.assertIsNotNone(result)
        self.assertEqual(result['entries'][0]['date'], '2026-11-12')

    def test_approval_without_immediately_presented_proposal_is_ignored(self):
        messages = [
            {'role':'user','content':'Schedule my one-on-one meeting tomorrow between 3pm and 4pm'},
            {'role':'assistant','content':'What else do you need to finish?'},
            {'role':'user','content':'approve it'},
        ]
        self.assertIsNone(riya_server.build_context_schedule(messages, self.tasks, '2026-11-11'))

if __name__ == '__main__':
    unittest.main(verbosity=2)
