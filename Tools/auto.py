from bot import Bot, Vars, logger
from .db import database
from TG.storage import get_episode_number, get_webs, igrone_error, queue
from .base import TaskCard, retry_on_flood
import asyncio
import gc

async def _should_send_chapter(chapters, lastest_sub_episode):
    """Check if new chapters need to be sent."""
    if not chapters:
        return

    first_chapter = chapters[0]
    if lastest_sub_episode in [None, "", " ", "None"]:
        yield first_chapter
        return

    if lastest_sub_episode == first_chapter.get('title', ''):
        return

    last_sub_num = get_episode_number(lastest_sub_episode)
    if not last_sub_num and lastest_sub_episode != first_chapter.get('title', ''):
        yield first_chapter

    if not last_sub_num:
        return

    for chapter in list(reversed(chapters)):
        chapter_num = get_episode_number(chapter.get('title', ''))
        if not chapter_num:
            continue

        try:
            # Convert to float for numeric comparison
            last_num = float(last_sub_num)
            chapter_num_float = float(chapter_num)

            if last_num != chapter_num_float and last_num < chapter_num_float:
                yield chapter
        except Exception:
            continue


async def _process_new_chapter(chapter, webs, url, user_id, num):
    """Process and send a new chapter update."""
    try:
        pictures = await igrone_error(webs.get_pictures)(chapter['url'], chapter)
        if not pictures:
            return None

        # Try to get user info for mention, but don't fail if we can't
        user_mention = f"<code>{user_id}</code>"
        try:
            user = await Bot.get_users(int(user_id))
            if user:
                user_mention = f"<code>{user_id}</code> [{user.mention()}]"
        except Exception:
            pass  # User not in cache or session issue

        message = (
            f"<b><i>Updates: {chapter.get('manga_title', 'Unknown')} - {chapter.get('title', 'Unknown')}</i></b>\n\n"
            f"Url: {chapter.get('url', 'N/A')}\n"
            f"Status: <code>Added At Queue</code>\n\n"
            f"User: {user_mention}"
        )

        sts = await retry_on_flood(Bot.send_message)(int(user_id), message)
        if not sts:  # User blocked bot or message failed
            return None

        await asyncio.sleep(3)

        if Vars.LOG_CHANNEL:
            log_msg = (
                f"<b><i>Updates: {chapter.get('manga_title', 'Unknown')} - {chapter.get('title', 'Unknown')}</i></b>\n\n"
                f"Url: {chapter.get('url', 'N/A')}\n\n"
                f"User: {user_mention}"
            )
            try:
                await retry_on_flood(Bot.send_message)(Vars.LOG_CHANNEL, log_msg)
            except Exception:
                pass

        user_settings = await database.get_settings(user_id)
        task_card = TaskCard(
            data_list=[chapter.copy()],
            picturesList=pictures,
            webs=webs,
            sts=sts,
            user_id=int(user_id),
            chat_id=int(user_id),
            priority=1,
            tasks_id=f"U_{user_id[3:] if len(user_id) > 3 else user_id}_{num}",
            update_mode=True,
            settings=user_settings,
        )

        p_data = {
            'url': url,
            'title': chapter.get("manga_title", ""),
            'lastest_chapter': chapter.get("title", "")
        }
        await database.save_latest_chapter(p_data, str(user_id), webs.sf)

        await queue.put(task_card, True)

        return True

    except Exception as err:
        err_str = str(err).lower()
        # Skip users who blocked bot, have invalid peer, or session issues
        if any(x in err_str for x in ["403", "blocked", "peer_id_invalid", "auth_key"]):
            logger.warning(f"Skipping user {user_id}: {err}")
            return None

        logger.exception(f"Error processing chapter: {err}")

        return False


async def check_subscribed_users(subs_parmas, num=0):
    """Check for updates for subscribed users."""
    updated_count = 0

    user_id, sf, sub_list = subs_parmas
    for sdata in sub_list:
        webs = get_webs(sf)
        if not webs:
            continue

        url = sdata.get('url')
        if not url:
            continue

        try:
            wdata = {"url": url, "title": sdata.get("title", "")}
            chapters = await webs.get_chapters(wdata, page=1)
            chapters = await asyncio.to_thread(lambda: webs.iter_chapters(chapters, page=1))
            lastest_sub_episode = sdata.get('lastest_chapter', None)

            async for chapter in _should_send_chapter(chapters, lastest_sub_episode):
                result = await _process_new_chapter(chapter, webs, url, user_id, num + updated_count)
                if result is None:  # User blocked bot
                    break
                if result:  # Successfully processed
                    updated_count += 1

                await asyncio.sleep(0.5)
        except KeyError:
            logger.error(f" CHeck Format Of {webs.__name__}")

        except Exception as err:
            logger.exception(f"Error checking updates for user {user_id}: {err}")

        await asyncio.sleep(1.5)
    return updated_count



async def get_updates_manga(num=0):
    """Check for manga updates for all subscribed users."""
    total_updated = 0
    async def process_subs(subs_list):
        return await check_subscribed_users(subs_list, total_updated)


    async for user_settings in database.get_all_subs():
        process_tasks = []

        subs_data = user_settings.get('subs', {})
        for sf, subs_list in list(subs_data.items()):
            process_params = (user_settings.get('_id'), sf, subs_list)

            process_tasks.append(
                asyncio.wait_for(process_subs(process_params), 10*60)
            )
            if len(process_tasks) % 3 == 0:
                results = await asyncio.gather(*process_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, int):
                        total_updated += result

                process_tasks = []

        # Do remaing process tasks
        if process_tasks:
            results = await asyncio.gather(*process_tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, int):
                    total_updated += result




    return total_updated