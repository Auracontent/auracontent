import time
import requests
import random
from config.settings import PEXELS_API_KEY, PIXABAY_API_KEY
from auracontent.utils.scraping_helpers import is_used, mark_used, download_file


class VideoProvider:
    def __init__(self, history):
        self.history = history

    def fetch_background(self, query, output_path):
        print(f"🎥 Recherche vidéo d'ambiance pour : '{query}'...")
        if self._fetch_from_pexels(query, output_path):
            return True
        if self._fetch_from_pixabay(query, output_path):
            return True
        return False

    def _fetch_from_pexels(self, query, output_path):
        if not PEXELS_API_KEY:
            print("ℹ️ PEXELS_API_KEY absente : Pexels ignoré.")
            return False
        url = "https://api.pexels.com/videos/search"
        params = {"query": query, "orientation": "portrait", "per_page": 15}
        headers = {"Authorization": PEXELS_API_KEY}

        try:
            r = requests.get(url, headers=headers, params=params, timeout=15)
            if r.status_code != 200:
                print(f"❌ Pexels HTTP {r.status_code} : {r.text[:150]}")
            else:
                videos = r.json().get("videos", [])
                random.shuffle(videos)
                
                for video in videos:
                    video_id = str(video.get("id"))
                    if is_used(self.history, "pexels", video_id):
                        continue

                    # Cherche le meilleur fichier (HD vertical)
                    files = video.get("video_files", [])
                    files.sort(key=lambda x: (x.get("width", 0) >= 1080, x.get("quality", "") == "hd"), reverse=True)
                    
                    if files and download_file(files[0]["link"], output_path):
                        mark_used(self.history, "pexels", video_id)
                        print("✅ Vidéo trouvée sur Pexels.")
                        return True
                print(f"ℹ️ Pexels : aucune vidéo neuve pour '{query}' ({len(videos)} résultats).")
        except Exception as e:
            print(f"❌ Erreur Pexels : {e}")
        return False

    def _fetch_from_pixabay(self, query, output_path):
        if not PIXABAY_API_KEY:
            print("ℹ️ PIXABAY_API_KEY absente : Pixabay ignoré.")
            return False
            
        url = "https://pixabay.com/api/videos/"
        params = {"key": PIXABAY_API_KEY, "q": query, "video_type": "film", "per_page": 15}

        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                print(f"❌ Pixabay HTTP {r.status_code} : {r.text[:150]}")
            else:
                hits = r.json().get("hits", [])
                random.shuffle(hits)
                
                for hit in hits:
                    video_id = str(hit.get("id"))
                    if is_used(self.history, "pixabay", video_id):
                        continue

                    videos = hit.get("videos", {})
                    # Privilégie la version Large
                    best_url = videos.get("large", {}).get("url") or videos.get("medium", {}).get("url")
                    
                    if best_url and download_file(best_url, output_path):
                        mark_used(self.history, "pixabay", video_id)
                        print("✅ Vidéo trouvée sur Pixabay.")
                        return True
                print(f"ℹ️ Pixabay : aucune vidéo neuve pour '{query}' ({len(hits)} résultats).")
        except Exception as e:
            print(f"❌ Erreur Pixabay : {e}")
        return False