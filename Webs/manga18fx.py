
from .scraper import Scraper
import json

from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin, quote, quote_plus

import re
from loguru import logger
from .utitls import DEAULT_MSG_FORMAT


class Manga18fxWebs(Scraper):
  def __init__(self):
    super().__init__()
    self.url = "https://manga18fx.com/"
    self.bg = None
    self.sf = "18fx"
    self.headers = {
      "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",

    }

  async def search(self, query: str = ""):
    url = f"https://manga18fx.com/search?q={quote_plus(query)}"
    mangas = await self.get(url)

    bs = BeautifulSoup(mangas, "html.parser") if mangas else None

    container = bs.find('div', {'class': 'listupd'}) if bs else None

    cards = container.find_all("div", {"class": "thumb-manga"}) if container else []

    results = []
    for card in cards:
      data = {}
      data['url'] = urljoin(self.url, card.findNext("a").get("href"))
      data['title'] = card.findNext("a").get("title")
      
      data['poster'] = card.findNext("img").get("src")
      results.append(data)

    return results

  async def get_chapters(self, data, page: int=1):
    results = data.copy()

    content = await self.get(results['url'])
    bs = BeautifulSoup(content, "html.parser") if content else None

    container = bs.find(class_="genres-content") if bs else None
    geners = container.text.strip() if container else "N/A"
    
    container = bs.find(class_="dsct")
    des = container.text.strip() if container else "N/A"

    results['msg'] = DEAULT_MSG_FORMAT.format(
      title=results['title'],
      status="N/A",
      genres=geners if geners else "N/A",
      summary=des[:400] if des else "N/A",
      url=results['url']
    )

    # cover: og:image first, then the summary image (lazy-load attributes before src); absolute URL
    if not results.get("poster"):
      from Tools.details import pick_cover
      cover = pick_cover(bs, results['url'], results.get('title', ''))
      if not cover:
        box = bs.find(class_="summary_image")
        img = box.find("img") if box else None
        for attr in ("data-src", "data-lazy-src", "src"):
          val = ((img.get(attr) if img else "") or "").strip()
          if val and not val.startswith("data:"):
            cover = val
            break
      results['poster'] = urljoin(self.url, cover.strip()) if cover else None

    genre_list = [a.text.strip() for a in (bs.find(class_="genres-content").find_all("a") if bs.find(class_="genres-content") else [])
                  if a.text and a.text.strip()]
    if not genre_list and geners and geners != "N/A":
      genre_list = [g.strip() for g in re.split(r"[,\n]", geners) if g.strip()]
    results['description'] = des if des and des != "N/A" else ""
    results['genres'] = genre_list
    results['status'] = ""
    
    chapters = bs.find("ul", {"class": "row-content-chapter"})
    chapters = chapters.find_all("li", {"class": "a-h"}) if chapters else []
    
    results['chapters'] = chapters

    return results


  def iter_chapters(self, data, page: int=1):
    chapters_list = []

    if 'chapters' in data:
     for card in data['chapters']:
       chapters_list.append({
         "title": card.find_next("a").text.strip(),
         "url": urljoin(self.url, card.find_next("a")['href']),
         "manga_title": data['title'],
         "poster": data['poster'] if 'poster' in data else None,
         "description": data.get('description', ""), "genres": data.get('genres', []),
         "status": data.get('status', ""),
         })
    
    return chapters_list[(page - 1) * 60:page * 60] if page != 1 else chapters_list

  async def get_pictures(self, url, data=None):
    content = await self.get(url)
    if not content:
      return None

    bs = BeautifulSoup(content, "html.parser")
    cards = bs.find_all("div", {"class": "page-break"})

    images_url = []
    for card in cards:
      img = card.find("img")           # THIS card's image (findNext could jump to the next card)
      if img is None:
        continue
      src = None
      for attr in ("data-src", "data-lazy-src", "data-original", "src"):   # lazy-load first, real src last
        val = (img.get(attr) or "").strip()
        if val and not val.startswith("data:"):
          src = val
          break
      if src:
        images_url.append(quote(urljoin(url, src), safe=':/%?=&'))

    return images_url or None
