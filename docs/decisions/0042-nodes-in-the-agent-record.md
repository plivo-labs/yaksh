# 0042 Nodes and moves in the agent record

Date: 2026-11-02
Status: accepted. Changes 0033 (a node is no longer left out).

## Context

- 0033 left the node out of the agent record. An agent of several nodes then reads to the judges as one flat agent.
- In tests of an agent of 7 nodes, the judges said a node did the work of another node: only the other node has the tool it called, so the call had moved first. They said the agent did not call `end_call`: the call ended through the `end_call` intent. A criterion about the order of the nodes could not be judged.
- Other providers have the same idea under other names: states, or sub-agents that hand off a call.

## Decision

- A record turn and a record tool get an optional `node`: the part of the agent that served the line, a node, state or sub-agent, as the provider names it. The record gets `moves`: the node the call came to, `via` (the provider's name for why it moved), its time and its place in the log. The first move is where the call started.
- Turns, tools and moves get `seq`, their place in the provider's log. A turn's place is where its speech started. Each tool and move comes before the first line that started after it; an equal or a missing time goes by `seq`.
- The server puts the lines in this order once. The API gives each line its `position`, and the console shows the lines by it, so the console and the judges always agree.
- The judges get one line for each move, and the turn lines do not change. A node name is thus never part of the words the agent said. A tool call of a node other than the one the last move came to names its node; for such a turn, a line before it names the node.
- Only the provider's reader knows the provider's rules. For Plivo CX: a move is a `NODE_EXECUTED` that is not the Start node; the end node's reply, logged under the node before it, belongs to the end node when its speech start comes after the move and its run ID is that of the node before.

## Why

- Move lines let a judge see which node acted, without a change to what the agent said.
- One order from the server gives the evidence view and the console the same order, also when times are equal after rounding to milliseconds.
- All fields are optional, so stored records and other providers read as before.

## Cost

- Evidence view version 10. Line numbers of a record with moves change, so the R-numbers of new and old evaluations of one agent differ.
- Records stored before this change keep no nodes: Yaksh reads a record once.

## Other options

- A node label on each turn and tool line in the evidence view. Rejected: a judge could quote the label as words the agent said.
- Separators only in the console, with no node on each line. Rejected: a line that comes late, such as the end node's reply, needs its own node.
