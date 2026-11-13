from pathlib import Path
import unittest

HTML = (Path(__file__).resolve().parents[1] / "RIYA.html").read_text(encoding="utf-8")

class PageNavigationTests(unittest.TestCase):
    def test_all_primary_pages_have_navigation(self):
        for page in ("home", "tasks", "schedule", "calendar", "history", "settings"):
            with self.subTest(page=page):
                self.assertIn(f'data-page="{page}"', HTML)
                self.assertIn(f'{page}:{page}View', HTML)

    def test_renderer_switches_between_separate_pages(self):
        self.assertIn("const pages={home:homeView,tasks:tasksView,schedule:scheduleView,calendar:calendarView,history:historyView,settings:settingsView}", HTML)
        self.assertIn("(pages[state.tab]||homeView)()", HTML)

    def test_desktop_layout_uses_fixed_app_shell_and_page_navigation(self):
        self.assertIn(".workspace{display:grid;grid-template-columns:190px", HTML)
        self.assertIn("html,body{height:100%;min-height:100%;overflow:hidden", HTML)
        self.assertIn(".page-nav{display:flex;flex-direction:column", HTML)

    def test_chat_only_renders_chat_controls(self):
        self.assertIn("if(state.tab==='home'){", HTML)
        self.assertIn("renderRiyaConversation();", HTML)

    def test_undated_conversation_tasks_are_visible_in_tasks_and_calendar(self):
        self.assertIn('Tasks awaiting a date', HTML)
        self.assertIn('Captured tasks without a date are shown here', HTML)
        self.assertIn("const undated=arr.filter(t=>!t.date", HTML)

    def test_schedule_uses_planner_pending_tasks_not_only_chat_drafts(self):
        self.assertIn("const draft=activeTasks().filter(t=>t.status==='pending'", HTML)

    def test_chat_task_sync_is_awaited_and_verified(self):
        self.assertIn('await syncRiyaTasksToPlanner(state.lastAiTasks)', HTML)
        self.assertIn('await persistAndVerify();', HTML)

    def test_startup_recovers_planner_tasks_from_conversation_memory(self):
        self.assertIn('Repair planner records from previously saved conversation working memory.', HTML)

if __name__ == "__main__":
    unittest.main()
