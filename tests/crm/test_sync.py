import uuid

from event_users.crm.sync import CrmSyncRunner, CrmSyncService
from event_users.dto.users import CreateUserContactDTO
from tests.conftest import FakeSession
from tests.crm.test_decrypt import KEY, encrypt


class FakeCrmClient:
    """Serves pre-encrypted pages."""

    def __init__(self, pages: list) -> None:
        self._pages = pages
        self.calls: list[int] = []

    async def fetch_users(self, page: int = 1, page_size: int = 100):  # noqa: ARG002
        self.calls.append(page)
        return self._pages[page - 1]


class FakeUsersDB:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, str]] = []

    async def upsert_user_from_crm(
        self,
        email: str,
        role: str,
        time_zone: str | None,  # noqa: ARG002
        name: str | None = None,  # noqa: ARG002
        contacts: list[CreateUserContactDTO] | None = None,  # noqa: ARG002
    ) -> None:
        self.upserts.append((email, role))


class FakeChangelog:
    def __init__(self, guarded: set[tuple[str, str]] | None = None) -> None:
        self.guarded = guarded or set()

    async def get_admin_changed_email_roles(self) -> set[tuple[str, str]]:
        return self.guarded


def multipage(page1_users: list[dict], page2_users: list[dict]) -> list:
    total = len(page1_users) + len(page2_users)
    p1 = encrypt(page1_users)
    p2 = encrypt(page2_users)
    # encrypt() sets total/page per payload; rebuild with paging metadata
    p1 = type(p1)(encrypted_data=p1.encrypted_data, iv=p1.iv, total=total, page=1, page_size=len(page1_users))
    p2 = type(p2)(encrypted_data=p2.encrypted_data, iv=p2.iv, total=total, page=2, page_size=len(page1_users))
    return [p1, p2]


def make_service(pages: list, guarded: set[tuple[str, str]] | None = None):
    session = FakeSession()
    db = FakeUsersDB()
    service = CrmSyncService(
        crm_client=FakeCrmClient(pages),
        session=session,
        db_adapter=db,
        changelog_adapter=FakeChangelog(guarded),
        encryption_key=KEY,
    )
    return service, session, db


async def test_sync_commits_once_per_page() -> None:
    pages = multipage(
        [{"email": "a@b.c", "role": "client"}],
        [{"email": "x@y.z", "role": "organizer"}],
    )
    service, session, db = make_service(pages)
    report = await service.sync()

    assert session.committed == 2  # one commit per page
    assert db.upserts == [("a@b.c", "client"), ("x@y.z", "organizer")]
    assert report.synced == 2
    assert report.quarantined == 0


async def test_sync_skips_admin_guarded_emails_without_per_user_queries() -> None:
    page = encrypt([{"email": "old@b.c", "role": "client"}, {"email": "ok@b.c", "role": "client"}])
    service, session, db = make_service([page], guarded={("old@b.c", "client")})
    report = await service.sync()

    assert db.upserts == [("ok@b.c", "client")]
    assert report.skipped_admin_guard == 1
    assert session.committed == 1


async def test_sync_counts_quarantined_records() -> None:
    page = encrypt([{"email": "ok@b.c", "role": "client"}, {"role": "client"}])
    service, _, db = make_service([page])
    report = await service.sync()

    assert db.upserts == [("ok@b.c", "client")]
    assert report.quarantined == 1


def test_runner_backoff_grows_and_caps() -> None:
    runner = CrmSyncRunner(
        crm_client=FakeCrmClient([]),
        sessionmaker=FakeSession,  # type: ignore[arg-type]
        encryption_key=KEY,
        interval=300,
        max_backoff=1800,
    )
    assert runner.next_delay() == 300  # healthy: regular interval
    runner.consecutive_failures = 1
    assert runner.next_delay() == 600
    runner.consecutive_failures = 2
    assert runner.next_delay() == 1200
    runner.consecutive_failures = 3
    assert runner.next_delay() == 1800
    runner.consecutive_failures = 50
    assert runner.next_delay() == 1800  # capped, no overflow


def make_uuid() -> uuid.UUID:
    return uuid.uuid4()
