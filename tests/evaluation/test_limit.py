import asyncio

from yaksh.evaluation.limit import Limit


async def test_a_smaller_limit_holds_new_work_until_it_fits_and_a_larger_one_lets_it_in() -> None:
    limit = Limit(2)
    entered: list[str] = []
    leave = {name: asyncio.Event() for name in ("a", "b", "c")}

    async def work(name: str) -> None:
        async with limit:
            entered.append(name)
            await leave[name].wait()

    first = [asyncio.create_task(work(name)) for name in ("a", "b")]
    await asyncio.sleep(0)
    await limit.resize(1)
    third = asyncio.create_task(work("c"))
    leave["a"].set()
    await first[0]
    await asyncio.sleep(0)
    held = list(entered)
    await limit.resize(2)
    await asyncio.sleep(0)
    for event in leave.values():
        event.set()
    await asyncio.gather(*first, third)

    assert held == ["a", "b"], "with one slot, c waits while b still runs"
    assert entered == ["a", "b", "c"]
