import re
import time
import asyncio
import datetime
import logging
from bson.objectid import ObjectId
from pymongo import InsertOne
from config import Config
from database.mongo import mongo

logger = logging.getLogger(__name__)

CAMRIP_PATTERNS = [
    r"\bcam\b", r"\bcamrip\b", r"\bpredvd\b", r"\bhdcam\b",
    r"\bhdts\b", r"\btelesync\b", r"\bdvdscr\b", r"\bcinema\b"
]

_LAST_DB1_CHECK_TIME = 0
_DB1_FULL_STATUS = False


async def check_storage_alerts(storage_mb: float):
    """Trigger tiered notifications (400MB, 420MB, 440MB) to Admins and Log Channel."""
    try:
        from database.mongo import get_bot_setting, set_bot_setting
        client = getattr(Config, "MASTER_CLIENT", None)
        if not client:
            return

        last_alert = await get_bot_setting("last_storage_alert_tier", "none")

        # Reset alert tier if database was cleared / pruned below 380 MB
        if storage_mb < 380:
            if last_alert != "none":
                await set_bot_setting("last_storage_alert_tier", "none")
            return

        tier_to_send = None
        alert_text = None
        pct = (storage_mb / 512.0) * 100

        if storage_mb >= 440 and last_alert != "440":
            tier_to_send = "440"
            if mongo.has_secondary:
                alert_text = (
                    "🚨 <b>MONGODB AUTO-ROUTING ACTIVATED • 440 MB</b> 🔴\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Primary DB (DB1):</b> <code>{storage_mb:.1f} MB / 512 MB ({pct:.1f}%)</code>\n"
                    "• <b>Secondary DB (DB2):</b> 🟢 Connected & Ready\n"
                    "• <b>Action:</b> Primary DB has crossed the 440 MB threshold. New file uploads are now <b>automatically saving into Secondary DB</b> to safeguard DB1 from reaching Atlas quota limits!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                alert_text = (
                    "🚨 <b>CRITICAL STORAGE ALERT • 440 MB REACHED</b> 🔴\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Primary DB (DB1):</b> <code>{storage_mb:.1f} MB / 512 MB ({pct:.1f}%)</code>\n"
                    "• <b>Secondary DB:</b> ⚪ Not Configured!\n\n"
                    "⚠️ <b>URGENT ACTION REQUIRED:</b>\n"
                    f"Primary MongoDB has only <b>~{512 - storage_mb:.1f} MB free space</b> left! Once 512 MB is reached, MongoDB will block all new file saves.\n"
                    "Please create a 2nd free MongoDB account and set <code>SECONDARY_DATABASE_URI</code> in <code>config.py</code> now!\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
        elif storage_mb >= 420 and storage_mb < 440 and last_alert not in ["420", "440"]:
            tier_to_send = "420"
            sec_status = "🟢 Ready for Auto-Switch" if mongo.has_secondary else "⚪ Not Added (Recommended Soon)"
            alert_text = (
                "⚠️ <b>MONGODB STORAGE WARNING • 420 MB REACHED</b> 🟠\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Primary DB (DB1):</b> <code>{storage_mb:.1f} MB / 512 MB ({pct:.1f}%)</code>\n"
                f"• <b>Secondary DB:</b> <code>{sec_status}</code>\n\n"
                "⚡ <b>Notice:</b> Primary DB is at 82% capacity. When it reaches 440 MB, automatic routing to DB2 will activate.\n"
                f"{'✅ Secondary DB is already configured and waiting.' if mongo.has_secondary else '💡 Tip: Set up a 2nd free MongoDB cluster and add SECONDARY_DATABASE_URI in config.py.'}\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
        elif storage_mb >= 400 and storage_mb < 420 and last_alert not in ["400", "420", "440"]:
            tier_to_send = "400"
            sec_status = "🟢 Connected" if mongo.has_secondary else "⚪ Not Configured"
            alert_text = (
                "📢 <b>MONGODB STORAGE ALERT • 400 MB REACHED</b> 🟡\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Primary DB (DB1):</b> <code>{storage_mb:.1f} MB / 512 MB ({pct:.1f}%)</code>\n"
                f"• <b>Secondary DB:</b> <code>{sec_status}</code>\n\n"
                "ℹ️ <b>Notice:</b> Primary MongoDB storage has reached 400 MB (78%). The bot will notify you again at 420 MB and 440 MB.\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )

        if tier_to_send and alert_text:
            await set_bot_setting("last_storage_alert_tier", tier_to_send)
            # Send to Log Channel
            if Config.LOG_CHANNEL:
                try:
                    await client.send_message(Config.LOG_CHANNEL, alert_text)
                except Exception as e:
                    logger.debug(f"Failed to send storage alert to log channel: {e}")
            # Send to Admins
            for admin_id in Config.ADMINS:
                try:
                    await client.send_message(admin_id, alert_text)
                except Exception as e:
                    logger.debug(f"Failed to send storage alert to admin {admin_id}: {e}")
    except Exception as ex:
        logger.error(f"Error in check_storage_alerts: {ex}")


async def get_active_target_collection() -> tuple:
    """Determine whether to save new media files into Primary DB or Secondary DB.
    Switches to Secondary DB when Primary DB storage reaches 440MB (or custom PRIMARY_DB_MAX_SIZE_MB).
    Triggers tiered admin alerts at 400MB, 420MB, and 440MB.
    Returns (target_collection, status_label).
    """
    global _LAST_DB1_CHECK_TIME, _DB1_FULL_STATUS

    # Check threshold periodically (cached every 120 seconds to avoid performance penalty)
    now = time.time()
    if now - _LAST_DB1_CHECK_TIME > 120:
        _LAST_DB1_CHECK_TIME = now
        try:
            max_mb = getattr(Config, "PRIMARY_DB_MAX_SIZE_MB", 440)
            db_stats = await mongo.db.command("dbStats")
            storage_mb = (db_stats.get("storageSize", 0) + db_stats.get("indexSize", 0)) / (1024 * 1024)
            if storage_mb >= max_mb:
                _DB1_FULL_STATUS = True
            else:
                _DB1_FULL_STATUS = False
            asyncio.create_task(check_storage_alerts(storage_mb))
        except Exception as e:
            logger.debug(f"Error checking DB1 threshold: {e}")

    if not mongo.has_secondary:
        return mongo.files, "primary"

    try:
        from database.mongo import get_bot_setting
        target_mode = await get_bot_setting("target_write_db", "auto")
        if target_mode == "1":
            return mongo.files, "primary (manual)"
        elif target_mode == "2":
            return mongo.files_secondary, "secondary (manual)"

        if _DB1_FULL_STATUS:
            return mongo.files_secondary, "secondary (auto-switched)"
        return mongo.files, "primary (auto)"
    except Exception as e:
        logger.error(f"Error in get_active_target_collection: {e}")
        return mongo.files, "primary"


async def save_file(media: dict) -> tuple[bool, str]:
    """Save media metadata to MongoDB, preventing duplicate entries across all connected clusters."""
    try:
        file_unique_id = media.get("file_unique_id")
        if not file_unique_id:
            return False, "Missing file_unique_id"

        file_size = media.get("file_size", 0)
        file_name = media.get("file_name", "Untitled")

        # 100% Exact Duplicate Check across Primary and Secondary DBs
        dup_query = [{"file_unique_id": file_unique_id}]
        if file_size > 0 and file_name and file_name != "Untitled":
            dup_query.append({"file_size": file_size, "file_name": file_name})

        # Check Primary
        existing = await mongo.files.find_one({"$or": dup_query})
        if existing:
            return False, "duplicate"

        # Check Secondary if connected
        if mongo.has_secondary:
            existing2 = await mongo.files_secondary.find_one({"$or": dup_query})
            if existing2:
                return False, "duplicate"

        file_doc = {
            "file_id": media.get("file_id"),
            "file_unique_id": file_unique_id,
            "file_name": file_name,
            "file_size": file_size,
            "file_type": media.get("file_type", "document"),
            "mime_type": media.get("mime_type", ""),
            "caption": media.get("caption", ""),
            "channel_id": media.get("channel_id"),
            "message_id": media.get("message_id"),
            "source": media.get("source", "auto_index"),
            "is_web_stream": media.get("is_web_stream", True),
            "created_at": datetime.datetime.utcnow()
        }

        target_col, _ = await get_active_target_collection()
        await target_col.insert_one(file_doc)
        return True, "saved"
    except Exception as e:
        logger.error(f"Error saving file to MongoDB: {e}")
        return False, str(e)


async def save_files_bulk(media_list: list[dict]) -> dict:
    """High-performance batch saver for channel indexer with duplicate prevention.
    Returns: {'saved': int, 'duplicate': int, 'errors': int, 'saved_media': list[dict]}
    """
    res = {"saved": 0, "duplicate": 0, "errors": 0, "saved_media": []}
    if not media_list:
        return res

    seen_uids = set()
    seen_name_sizes = set()
    valid_batch = []
    batch_uids = []
    name_size_queries = []

    for m in media_list:
        uid = m.get("file_unique_id")
        if not uid:
            res["errors"] += 1
            continue

        fname = m.get("file_name", "Untitled")
        fsize = m.get("file_size", 0)

        # In-batch duplicate check
        if uid in seen_uids:
            res["duplicate"] += 1
            continue
        if fsize > 0 and fname and fname != "Untitled" and (fname, fsize) in seen_name_sizes:
            res["duplicate"] += 1
            continue

        seen_uids.add(uid)
        if fsize > 0 and fname and fname != "Untitled":
            seen_name_sizes.add((fname, fsize))
            name_size_queries.append({"file_name": fname, "file_size": fsize})

        valid_batch.append(m)
        batch_uids.append(uid)

    if not valid_batch:
        return res

    existing_uids = set()
    existing_name_sizes = set()

    # Query existing duplicates in MongoDB
    query_conditions = [{"file_unique_id": {"$in": batch_uids}}]
    if name_size_queries:
        query_conditions.append({"$or": name_size_queries[:100]})

    async def scan_existing(col):
        try:
            cursor = col.find({"$or": query_conditions}, {"_id": 0, "file_unique_id": 1, "file_name": 1, "file_size": 1})
            async for doc in cursor:
                u = doc.get("file_unique_id")
                if u:
                    existing_uids.add(u)
                fn = doc.get("file_name")
                fs = doc.get("file_size")
                if fn and fs:
                    existing_name_sizes.add((fn, fs))
        except Exception as err:
            logger.debug(f"Error querying existing files: {err}")

    await scan_existing(mongo.files)
    if mongo.has_secondary:
        await scan_existing(mongo.files_secondary)

    # Determine files to insert
    target_col, _ = await get_active_target_collection()
    operations = []
    now_utc = datetime.datetime.utcnow()
    ready_to_save = []

    for m in valid_batch:
        uid = m.get("file_unique_id")
        fname = m.get("file_name", "Untitled")
        fsize = m.get("file_size", 0)

        if uid in existing_uids or (fname, fsize) in existing_name_sizes:
            res["duplicate"] += 1
            continue

        file_doc = {
            "file_id": m.get("file_id"),
            "file_unique_id": uid,
            "file_name": fname,
            "file_size": fsize,
            "file_type": m.get("file_type", "document"),
            "mime_type": m.get("mime_type", ""),
            "caption": m.get("caption", ""),
            "channel_id": m.get("channel_id"),
            "message_id": m.get("message_id"),
            "source": m.get("source", "bulk_index"),
            "is_web_stream": m.get("is_web_stream", False),
            "created_at": now_utc
        }
        operations.append(InsertOne(file_doc))
        ready_to_save.append(m)

    if operations:
        try:
            bulk_res = await target_col.bulk_write(operations, ordered=False)
            inserted = bulk_res.inserted_count
            res["saved"] = inserted
            res["saved_media"] = ready_to_save[:inserted]
        except Exception as e:
            logger.error(f"Error in bulk_write execution: {e}")
            for op in operations:
                try:
                    await target_col.insert_one(op._doc)
                    res["saved"] += 1
                except Exception:
                    res["errors"] += 1

    return res


async def clean_duplicate_files() -> tuple[int, int]:
    """Scan MongoDB files collections across all connected clusters for 100% exact duplicate files.
    Keeps the earliest/primary document and deletes all extra duplicate copies.
    Returns (total_deleted, total_unique_preserved).
    """
    total_deleted = 0
    seen_unique_ids = set()
    seen_name_size = set()

    for col in mongo.all_files_collections:
        to_delete_ids = []
        cursor = col.find({}, {"_id": 1, "file_unique_id": 1, "file_name": 1, "file_size": 1}).sort("_id", 1)

        async for doc in cursor:
            doc_id = doc["_id"]
            f_uid = doc.get("file_unique_id")
            f_name = (doc.get("file_name") or "").strip().lower()
            f_size = doc.get("file_size") or 0

            is_dup = False
            if f_uid and f_uid in seen_unique_ids:
                is_dup = True
            elif f_name and f_size > 0 and (f_name, f_size) in seen_name_size:
                is_dup = True

            if is_dup:
                to_delete_ids.append(doc_id)
                if len(to_delete_ids) >= 500:
                    res = await col.delete_many({"_id": {"$in": to_delete_ids}})
                    total_deleted += res.deleted_count
                    to_delete_ids = []
            else:
                if f_uid:
                    seen_unique_ids.add(f_uid)
                if f_name and f_size > 0:
                    seen_name_size.add((f_name, f_size))

        if to_delete_ids:
            res = await col.delete_many({"_id": {"$in": to_delete_ids}})
            total_deleted += res.deleted_count

    total_unique_preserved = len(seen_unique_ids) or len(seen_name_size)
    return total_deleted, total_unique_preserved


QUALITY_PATTERNS = {
    "480p": r"(480p|sd\b)",
    "720p": r"(720p|hd\b)",
    "1080p": r"(1080p|fhd\b)",
    "2160p": r"(2160p|4k|uhd)",
}

LANGUAGE_PATTERNS = {
    "hindi": r"(hindi|hin\b)",
    "english": r"(english|eng\b)",
    "tamil": r"(tamil|tam\b)",
    "telugu": r"(telugu|tel\b)",
    "malayalam": r"(malayalam|mal\b)",
    "kannada": r"(kannada|kan\b)",
    "dual": r"(dual|multi)",
}

SEASON_PATTERNS = {
    "s01": r"(s01\b|season[\s\._-]*1\b|s1\b)",
    "s02": r"(s02\b|season[\s\._-]*2\b|s2\b)",
    "s03": r"(s03\b|season[\s\._-]*3\b|s3\b)",
    "s04": r"(s04\b|season[\s\._-]*4\b|s4\b)",
    "s05": r"(s05\b|season[\s\._-]*5\b|s5\b)",
    "s06": r"(s06\b|season[\s\._-]*6\b|s6\b)",
}

COMPOUND_WORDS = {
    "ironman": r"iron[\s\.\-_]*man",
    "spiderman": r"spider[\s\.\-_]*man",
    "batman": r"bat[\s\.\-_]*man",
    "superman": r"super[\s\.\-_]*man",
    "deadpool": r"dead[\s\.\-_]*pool",
    "aquaman": r"aqua[\s\.\-_]*man",
    "antman": r"ant[\s\.\-_]*man",
    "starwars": r"star[\s\.\-_]*wars",
    "topgun": r"top[\s\.\-_]*gun",
    "startrek": r"star[\s\.\-_]*trek",
    "kingsman": r"kings[\s\.\-_]*man",
    "pacman": r"pac[\s\.\-_]*man",
}

def _token_to_regex(token: str) -> str:
    """Convert search token into a flexible regex matching spaces, dots, and common compounding."""
    t_lower = token.lower()
    if t_lower in COMPOUND_WORDS:
        return COMPOUND_WORDS[t_lower]
    # Flexible matching for short acronyms like kgf -> k[\.\s\-_]*g[\.\s\-_]*f, rrr, pk, etc.
    if 2 <= len(token) <= 4 and token.isalpha():
        return r"[\.\s\-_]*".join(list(re.escape(token)))
    return re.escape(token)

def _extract_query_episode_target(query: str) -> int | None:
    """Extract requested episode number from query if present (e.g. 'Sweet Teeth 5' -> 5)."""
    if not query:
        return None
    tokens = re.findall(r"[\w']+", query)
    for t in tokens:
        m = re.match(r"^(?:e|ep|episode)?0*(\d{1,3})$", t, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def _score_file_relevance(file_name: str, target_ep: int | None) -> int:
    """Score file higher if it matches target episode directly or via combined range."""
    if target_ep is None or not file_name:
        return 0
    # Check exact episode match (e.g. E05, Ep 5, 05)
    if re.search(rf"\b(?:e|ep|episode)?\s*0*{target_ep}\b", file_name, re.IGNORECASE):
        return 100
    # Check range occurrence: [E01-11] or E01-11
    range_m = re.search(r'\[\s*(?:E|EP)?\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\s*\]', file_name, re.IGNORECASE)
    if not range_m:
        range_m = re.search(r'\b(?:E|EP)\s*(\d{1,3})\s*[-–to]+\s*(?:E|EP)?\s*(\d{1,3})\b', file_name, re.IGNORECASE)
    if range_m:
        start_ep, end_ep = int(range_m.group(1)), int(range_m.group(2))
        if start_ep <= target_ep <= end_ep:
            return 90
        return -50
    # Complete / season pack fallback
    if re.search(r"\b(COMBINED|COMPLETE|PACK|Season\s*\d+|S\d+)\b", file_name, re.IGNORECASE):
        return 50
    return 10


def _get_quality_rank(file_name: str) -> int:
    """Return quality hierarchy weight (4K > 1080p > 720p > 480p > Other)."""
    if not file_name:
        return 10
    fn = file_name.lower()
    if re.search(r"\b(2160p|4k|uhd)\b", fn):
        return 50
    if re.search(r"\b(1080p|fhd)\b", fn):
        return 40
    if re.search(r"\b(720p|hd)\b", fn):
        return 30
    if re.search(r"\b(480p|sd)\b", fn):
        return 20
    return 10


def _build_search_filter(query: str, quality: str = None, language: str = None, season: str = None) -> dict:
    """Constructs a MongoDB query filter with tokenized regex matching and sub-category constraints.
    Supports smart fallback for episode numbers to match combined/complete season packs.
    """
    filter_dict = {}

    if query:
        clean_tokens = re.findall(r"[\w']+", query)
        if clean_tokens:
            regex_patterns = []
            for token in clean_tokens:
                ep_match = re.match(r"^(?:e|ep|episode)?0*(\d{1,3})$", token, re.IGNORECASE)
                if ep_match:
                    num = int(ep_match.group(1))
                    # Token is an episode number or digit.
                    # Match exact episode (e.g. E05, Ep 5, 5) OR combined / complete / season packs!
                    ep_or_combined_regex = (
                        rf"(?:\b(?:e|ep|episode)?\s*0*{num}\b|"
                        rf"COMBINED|COMPLETE|PACK|Season\s*\d+|S\d+|"
                        rf"\[\s*(?:E|EP)?\s*\d+\s*[-–to]+\s*(?:E|EP)?\s*\d+\s*\])"
                    )
                    regex_patterns.append({"file_name": {"$regex": ep_or_combined_regex, "$options": "i"}})
                else:
                    pat = _token_to_regex(token)
                    regex_patterns.append({"file_name": {"$regex": pat, "$options": "i"}})
            filter_dict["$and"] = regex_patterns

    # Quality constraint
    if quality:
        quality_regex = QUALITY_PATTERNS.get(quality.lower(), re.escape(quality))
        filter_dict.setdefault("$and", []).append({"file_name": {"$regex": quality_regex, "$options": "i"}})

    # Language constraint
    if language:
        lang_regex = LANGUAGE_PATTERNS.get(language.lower(), re.escape(language))
        filter_dict.setdefault("$and", []).append({"file_name": {"$regex": lang_regex, "$options": "i"}})

    # Season constraint
    if season:
        season_regex = SEASON_PATTERNS.get(season.lower(), re.escape(season))
        filter_dict.setdefault("$and", []).append({"file_name": {"$regex": season_regex, "$options": "i"}})

    return filter_dict


async def get_search_results(query: str, offset: int = 0, limit: int = 10, quality: str = None, language: str = None, season: str = None) -> list:
    """Retrieve paginated file search results from MongoDB matching query and filters.
    If Secondary MongoDB is connected, queries both clusters concurrently via asyncio.gather and merges results.
    """
    try:
        filter_dict = _build_search_filter(query, quality, language, season)
        if not mongo.has_secondary:
            cursor = mongo.files.find(filter_dict).sort([("_id", -1)]).skip(offset).limit(limit)
            results = await cursor.to_list(length=limit)
        else:
            fetch_limit = offset + limit
            task1 = mongo.files.find(filter_dict).sort([("_id", -1)]).limit(fetch_limit).to_list(length=fetch_limit)
            task2 = mongo.files_secondary.find(filter_dict).sort([("_id", -1)]).limit(fetch_limit).to_list(length=fetch_limit)
            res1, res2 = await asyncio.gather(task1, task2, return_exceptions=True)

            docs1 = res1 if isinstance(res1, list) else []
            docs2 = res2 if isinstance(res2, list) else []

            seen_uids = set()
            combined = []
            for doc in docs1 + docs2:
                uid = doc.get("file_unique_id") or str(doc.get("_id"))
                if uid not in seen_uids:
                    seen_uids.add(uid)
                    combined.append(doc)

            combined.sort(key=lambda doc: doc.get("created_at") or datetime.datetime.min, reverse=True)
            results = combined[offset : offset + limit]

        # Smart re-ranking if search query contains an episode number
        target_ep = _extract_query_episode_target(query)
        if target_ep is not None and results:
            results.sort(key=lambda doc: _score_file_relevance(doc.get("file_name", ""), target_ep), reverse=True)
        elif results:
            # If results contain multi-part movie files, ensure Part 1 comes before Part 2
            from utils.helpers import parse_media_metadata
            has_parts = any(parse_media_metadata(d.get("file_name", "")).get("is_part") for d in results)
            if has_parts:
                def part_order(doc):
                    m = parse_media_metadata(doc.get("file_name", ""))
                    p = m.get("part") if m.get("is_part") else 0
                    return p if p > 0 else 999
                results.sort(key=part_order)
            elif not quality:
                # Smart Quality Sorting: Prioritize highest resolution (4K UHD > 1080p > 720p > 480p)
                results.sort(key=lambda doc: _get_quality_rank(doc.get("file_name", "")), reverse=True)

        return results
    except Exception as e:
        logger.error(f"Error fetching search results: {e}")
        return []


async def get_related_files(file_name: str, current_file_id: str = None, limit: int = 6) -> list:
    """Find 4-6 related/recent files from MongoDB across all clusters excluding current title."""
    try:
        from utils.helpers import parse_media_metadata
        meta = parse_media_metadata(file_name)
        clean_name = meta.get("clean_name", "")

        exclude_conditions = []
        if current_file_id:
            exclude_conditions.append({"file_unique_id": {"$ne": current_file_id}})
        if clean_name and len(clean_name) >= 3:
            exclude_conditions.append({"file_name": {"$not": {"$regex": f"^{re.escape(clean_name)}", "$options": "i"}}})
        elif file_name:
            exclude_conditions.append({"file_name": {"$ne": file_name}})

        filter_dict = {"$and": exclude_conditions} if exclude_conditions else {}

        if not mongo.has_secondary:
            cursor = mongo.files.find(filter_dict).sort("created_at", -1).limit(limit)
            return await cursor.to_list(length=limit)

        task1 = mongo.files.find(filter_dict).sort("created_at", -1).limit(limit).to_list(length=limit)
        task2 = mongo.files_secondary.find(filter_dict).sort("created_at", -1).limit(limit).to_list(length=limit)
        r1, r2 = await asyncio.gather(task1, task2, return_exceptions=True)
        docs1 = r1 if isinstance(r1, list) else []
        docs2 = r2 if isinstance(r2, list) else []
        combined = docs1 + docs2
        combined.sort(key=lambda d: d.get("created_at") or datetime.datetime.min, reverse=True)
        return combined[:limit]
    except Exception as e:
        logger.error(f"Error fetching related files: {e}")
        return []


async def count_files(query: str, quality: str = None, language: str = None, season: str = None) -> int:
    """Count total files matching the query and sub-filters across all clusters for pagination."""
    try:
        filter_dict = _build_search_filter(query, quality, language, season)
        if not mongo.has_secondary:
            return await mongo.files.count_documents(filter_dict)

        c1, c2 = await asyncio.gather(
            mongo.files.count_documents(filter_dict),
            mongo.files_secondary.count_documents(filter_dict),
            return_exceptions=True
        )
        count1 = c1 if isinstance(c1, int) else 0
        count2 = c2 if isinstance(c2, int) else 0
        return count1 + count2
    except Exception as e:
        logger.error(f"Error counting files: {e}")
        return 0


async def get_file_by_id(file_identifier: str) -> dict | None:
    """Fetch file metadata by Telegram file_unique_id, file_id, or MongoDB _id across all clusters."""
    try:
        conditions = [
            {"file_unique_id": file_identifier},
            {"file_id": file_identifier}
        ]
        if ObjectId.is_valid(file_identifier):
            conditions.append({"_id": ObjectId(file_identifier)})
        query = {"$or": conditions}

        doc = await mongo.files.find_one(query)
        if doc:
            return doc

        if mongo.has_secondary:
            doc2 = await mongo.files_secondary.find_one(query)
            if doc2:
                return doc2

        # 3. Fallback to searching inside batches collection
        batch = await mongo.batches.find_one({
            "$or": [
                {"files.file_unique_id": file_identifier},
                {"files.file_id": file_identifier}
            ]
        })
        if batch:
            for f in batch.get("files", []):
                if f.get("file_unique_id") == file_identifier or f.get("file_id") == file_identifier:
                    return f

        return None
    except Exception as e:
        logger.error(f"Error retrieving file by ID {file_identifier}: {e}")
        return None


async def delete_file_by_id(file_identifier: str) -> bool:
    """Delete a specific file from MongoDB by ID across all clusters."""
    try:
        is_obj_id = ObjectId.is_valid(file_identifier)
        query = {"_id": ObjectId(file_identifier)} if is_obj_id else {
            "$or": [
                {"file_unique_id": file_identifier},
                {"file_id": file_identifier}
            ]
        }

        res = await mongo.files.delete_one(query)
        if res.deleted_count > 0:
            return True

        if mongo.has_secondary:
            res2 = await mongo.files_secondary.delete_one(query)
            return res2.deleted_count > 0

        return False
    except Exception as e:
        logger.error(f"Error deleting file {file_identifier}: {e}")
        return False


async def delete_camrip_files() -> int:
    """Bulk purge low-quality CamRip, PreDVD, HDCam, and Telesync files across all clusters."""
    try:
        cam_regex = "|".join(CAMRIP_PATTERNS)
        res1 = await mongo.files.delete_many({"file_name": {"$regex": cam_regex, "$options": "i"}})
        total = res1.deleted_count
        if mongo.has_secondary:
            res2 = await mongo.files_secondary.delete_many({"file_name": {"$regex": cam_regex, "$options": "i"}})
            total += res2.deleted_count
        logger.info(f"Purged {total} CamRip/PreDVD files from MongoDB.")
        return total
    except Exception as e:
        logger.error(f"Error deleting CamRip files: {e}")
        return 0


async def delete_all_files() -> int:
    """Full database purge of all indexed files across all clusters."""
    global _DB1_FULL_STATUS, _LAST_DB1_CHECK_TIME
    try:
        res1 = await mongo.files.delete_many({})
        total = res1.deleted_count
        if mongo.has_secondary:
            res2 = await mongo.files_secondary.delete_many({})
            total += res2.deleted_count
        _DB1_FULL_STATUS = False
        _LAST_DB1_CHECK_TIME = 0
        from database.mongo import set_bot_setting
        await set_bot_setting("last_storage_alert_tier", "none")
        return total
    except Exception as e:
        logger.error(f"Error purging all files: {e}")
        return 0


async def purge_files_and_caches() -> dict:
    """Purge all indexed media files and cache bloat (TMDB cache, channel posts, checkpoints, verifications)
    across all MongoDB clusters. Safely drops database storage footprint to ~0 MB while preserving users,
    VIP subscriptions, and bot settings.
    """
    global _DB1_FULL_STATUS, _LAST_DB1_CHECK_TIME
    stats = {
        "files_primary": 0,
        "files_secondary": 0,
        "tmdb_cache": 0,
        "channel_posts": 0,
        "checkpoints": 0,
        "verifications": 0,
        "total": 0
    }
    try:
        # 1. Primary files
        res1 = await mongo.files.delete_many({})
        stats["files_primary"] = res1.deleted_count

        # 2. Secondary files (if connected)
        if mongo.has_secondary:
            res2 = await mongo.files_secondary.delete_many({})
            stats["files_secondary"] = res2.deleted_count

        # 3. TMDB post cache
        try:
            res_tmdb = await mongo.db["tmdb_post_cache"].delete_many({})
            stats["tmdb_cache"] = res_tmdb.deleted_count
        except Exception as e:
            logger.warning(f"Error purging tmdb_post_cache: {e}")

        # 4. Channel post mappings
        try:
            res_cp = await mongo.db["channel_posts"].delete_many({})
            stats["channel_posts"] = res_cp.deleted_count
        except Exception as e:
            logger.warning(f"Error purging channel_posts: {e}")

        # 5. Indexer checkpoints
        try:
            res_chk = await mongo.db["indexer_checkpoints"].delete_many({})
            stats["checkpoints"] = res_chk.deleted_count
        except Exception as e:
            logger.warning(f"Error purging indexer_checkpoints: {e}")

        # 6. Verifications
        try:
            res_v = await mongo.verify.delete_many({})
            stats["verifications"] = res_v.deleted_count
        except Exception as e:
            logger.warning(f"Error purging verifications: {e}")

        stats["total"] = (
            stats["files_primary"] + stats["files_secondary"] +
            stats["tmdb_cache"] + stats["channel_posts"] +
            stats["checkpoints"] + stats["verifications"]
        )

        # Reset global memory flags and database storage alert tier
        _DB1_FULL_STATUS = False
        _LAST_DB1_CHECK_TIME = 0
        from database.mongo import set_bot_setting
        await set_bot_setting("last_storage_alert_tier", "none")

        logger.info(f"Database purge_files_and_caches completed: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Error executing purge_files_and_caches: {e}", exc_info=True)
        return stats


async def purge_factory_reset() -> dict:
    """Full factory reset: Purges files, caches, batches, secret share links, movie requests,
    upload alerts, and manual filters. Keeps user registrations, VIP accounts, and bot credentials safe.
    """
    stats = await purge_files_and_caches()
    extra_stats = {
        "batches": 0,
        "share_links": 0,
        "movie_requests": 0,
        "upload_alerts": 0,
        "manual_filters": 0,
        "downloader_stats": 0
    }
    try:
        try:
            res_b = await mongo.batches.delete_many({})
            extra_stats["batches"] = res_b.deleted_count
        except Exception:
            pass

        try:
            res_sl = await mongo.share_links.delete_many({})
            extra_stats["share_links"] = res_sl.deleted_count
        except Exception:
            pass

        try:
            res_req = await mongo.requests.delete_many({})
            extra_stats["movie_requests"] = res_req.deleted_count
        except Exception:
            pass

        try:
            res_ua = await mongo.db["upload_alerts"].delete_many({})
            extra_stats["upload_alerts"] = res_ua.deleted_count
        except Exception:
            pass

        try:
            res_mf = await mongo.filters.delete_many({})
            extra_stats["manual_filters"] = res_mf.deleted_count
        except Exception:
            pass

        try:
            res_ds = await mongo.dl_stats.delete_many({})
            extra_stats["downloader_stats"] = res_ds.deleted_count
        except Exception:
            pass

        stats.update(extra_stats)
        stats["total"] += sum(extra_stats.values())
        logger.info(f"Database purge_factory_reset completed: {stats}")
        return stats
    except Exception as e:
        logger.error(f"Error executing purge_factory_reset: {e}", exc_info=True)
        return stats


async def get_total_files_count() -> int:
    """Get total count of indexed media files across all connected clusters."""
    try:
        if not mongo.has_secondary:
            return await mongo.files.count_documents({})

        c1, c2 = await asyncio.gather(
            mongo.files.count_documents({}),
            mongo.files_secondary.count_documents({}),
            return_exceptions=True
        )
        return (c1 if isinstance(c1, int) else 0) + (c2 if isinstance(c2, int) else 0)
    except Exception as e:
        logger.error(f"Error getting total files count: {e}")
        return 0


async def get_sample_titles(limit: int = 3000) -> list[str]:
    """Retrieve sample file titles for fuzzy matching and spell-checking index across all clusters.
    Sorts by recent uploads (_id desc) to ensure latest catalog is prioritized in suggestions.
    """
    try:
        if not mongo.has_secondary:
            cursor = mongo.files.find({}, {"file_name": 1}).sort([("_id", -1)]).limit(limit)
            docs = await cursor.to_list(length=limit)
            return [doc.get("file_name", "") for doc in docs if doc.get("file_name")]

        half = max(1, limit // 2)
        task1 = mongo.files.find({}, {"file_name": 1}).sort([("_id", -1)]).limit(half).to_list(length=half)
        task2 = mongo.files_secondary.find({}, {"file_name": 1}).sort([("_id", -1)]).limit(half).to_list(length=half)
        r1, r2 = await asyncio.gather(task1, task2, return_exceptions=True)
        docs1 = r1 if isinstance(r1, list) else []
        docs2 = r2 if isinstance(r2, list) else []
        return [doc.get("file_name", "") for doc in (docs1 + docs2) if doc.get("file_name")]
    except Exception as e:
        logger.error(f"Error retrieving titles for spellcheck: {e}")
        return []
