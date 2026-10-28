from yaksh.domain.scenarios import DataSet, Fact, Interruption, ScenarioConfig


def test_a_played_scenario_fills_the_facts_of_its_data_set_into_each_interruption() -> None:
    priya = DataSet(name="Priya", known_facts=[Fact(name="Card", value="4242")])
    rahul = DataSet(name="Rahul", known_facts=[Fact(name="Card", value="1881")])
    config = ScenarioConfig(
        instructions="Pay with your card.",
        criteria=["Reads back the card."],
        data_sets=[priya, rahul],
        interruptions=[
            Interruption(say="Wait, not {{Card}}.", agent_says="ending in {{Card}}"),
            Interruption(say="Mm-hmm.", from_answer=3),
        ],
    )

    played = config.played(rahul.id).interruptions

    assert [(item.say, item.agent_says) for item in played] == [
        ("Wait, not 1881.", "ending in 1881"),
        ("Mm-hmm.", None),
    ]
    assert [(item.after_s, item.from_answer) for item in played] == [(0.0, 1), (2.0, 3)]
