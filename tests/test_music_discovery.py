import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
import json
import threading
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'music_collector.pyw'
loader = importlib.machinery.SourceFileLoader('discovery', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

def close_test_root(root):
    root.update_idletasks()
    for pending in root.tk.call('after', 'info'):
        root.after_cancel(pending)
    root.destroy()

class DiscoveryTests(unittest.TestCase):
    def test_search_replaces_previous_results_without_touching_files(self):
        original_data, original_crawl = m.DATA, m.crawl
        with tempfile.TemporaryDirectory() as tmp:
            m.DATA = Path(tmp)
            root = m.tk.Tk()
            root.attributes('-alpha', 0)
            try:
                app = m.App(root)
                item = {'url':'https://example.test/old.flac','name':'old','kind':'音频直链','code':'','source':'https://example.test/','status':'完成'}
                app.add_item(item)
                app.favorite_ids.add('r00')
                music = Path(tmp) / 'already-downloaded.flac'
                music.write_bytes(b'fLaC-do-not-touch')
                app.sources.insert('1.0', 'invalid-address')
                with patch.object(m.messagebox, 'showerror'):
                    app.start_crawl()
                self.assertIn(item['url'], app.items)
                app.sources.delete('1.0', 'end')
                finished = threading.Event()
                observed = []
                def fake_crawl(seeds, keyword, limit, depth, cancel, emit):
                    observed.append(len(app.items))
                    emit('resource', dict(item, url='https://example.test/new.flac', name='new'))
                    emit('crawl_done', None)
                    finished.set()
                m.crawl = fake_crawl
                app.downloading = True
                app.start_crawl()
                self.assertTrue(finished.wait(2))
                self.assertEqual(observed, [0])
                self.assertEqual(app.tree.get_children(), ())
                app.poll()
                self.assertEqual(set(app.items), {'https://example.test/new.flac'})
                self.assertIn('r00', app.favorite_ids)
                self.assertEqual(music.read_bytes(), b'fLaC-do-not-touch')
                self.assertTrue(app.downloading)
            finally:
                close_test_root(root)
                m.DATA, m.crawl = original_data, original_crawl

    def test_source_upgrade_preserves_choices_and_adds_new_sites(self):
        original_data = m.DATA
        with tempfile.TemporaryDirectory() as tmp:
            m.DATA = Path(tmp)
            (m.DATA/'settings.json').write_text(json.dumps({'selected_sites':['https://hifini.net/']}))
            root = m.tk.Tk()
            root.attributes('-alpha', 0)
            try:
                app = m.App(root)
                new = {url for _,url,_ in m.BUILTIN_SITES[8:]}
                self.assertEqual(len(new),7)
                self.assertTrue(new <= app.selected_sites)
                self.assertIn('https://hifini.net/', app.selected_sites)
                self.assertNotIn('http://www.23ape.net/', app.selected_sites)
                app.choose_sites()
                root.update()
            finally:
                close_test_root(root)
                m.DATA = original_data

    def test_combined_categories_and_no_silent_fallback(self):
        pool = m.recommendation_pool('华语', '摇滚', '氛围')
        self.assertTrue(pool)
        self.assertTrue(all(item['region'] == '华语' and item['genre'] == '摇滚' and item['mood'] == '氛围' for item in pool))
        self.assertEqual(m.recommendation_pool('日韩', '古典', '专注'), [])
    def test_fresh_batch_and_favorites_filter(self):
        pool = m.recommendation_pool()
        first = m.pick_recommendations(pool)
        next_batch = m.pick_recommendations(pool, [item['id'] for item in first])
        self.assertFalse({i['id'] for i in first} & {i['id'] for i in next_batch})
        self.assertEqual(m.recommendation_pool(favorites={pool[0]['id']}), [pool[0]])
        self.assertEqual(m.recommendation_pool(favorites=set()), [])
    def test_ui_favorites_persistence_and_search_handoff(self):
        original_data = m.DATA
        with tempfile.TemporaryDirectory() as tmp:
            m.DATA = Path(tmp)
            root = m.tk.Tk()
            root.attributes('-alpha', 0)
            root.tk.call('tk', 'scaling', 2.0)
            try:
                app = m.App(root)
                root.update()
                self.assertEqual(len(app.recommendation_ids), 6)
                item = next(i for i in m.RECOMMENDATIONS if i['id'] == app.recommendation_ids[0])
                original_batch = app.recommendation_ids[:]
                app.toggle_favorite(item)
                self.assertEqual(app.recommendation_ids, original_batch)
                self.assertIn(item['id'], app.favorite_ids)
                saved = json.loads(app.config_path.read_text('utf-8'))
                self.assertIn(item['id'], saved['favorite_recommendations'])
                app.only_favorites.set(True)
                app.refresh_discovery()
                self.assertEqual(app.recommendation_ids, [item['id']])
                app.use_recommendation(item, False)
                self.assertEqual(app.keyword.get(), item['query'])
                self.assertEqual(app.notebook.select(), str(app.collect_tab))
                root.update()
                self.assertTrue(app.log_widget.winfo_ismapped())
                self.assertLess(app.log_widget.winfo_y() + app.log_widget.winfo_height(), root.winfo_height())
                app.notebook.select(app.discover_tab)
                app.toggle_favorite(item)
                self.assertEqual(app.recommendation_ids, [])
                app.reset_discovery()
                self.assertEqual(len(app.recommendation_ids), 6)
            finally:
                close_test_root(root)
                m.DATA = original_data

if __name__ == '__main__':
    unittest.main(verbosity=2)
