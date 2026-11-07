# Block inventory database

Supabase project **sidekick-blocks** (region us-east-2), one table: `public.block_inventory`.
It is a team record of the physical wooden blocks. The Sidekick code does **not** read it; it reads `sidekick/catalog.py` / `sidekick_data/blocks.json`.

- Dashboard: https://supabase.com/dashboard/project/ykevkqzxuthubvbqkcld/editor
- Project ref: `ykevkqzxuthubvbqkcld`

## Columns

| Column | Meaning |
|---|---|
| `type_id` | block type: `cube`, `pillar`, `plank`, `bar`, `cyl_short`, `cyl_tall`, `arch`, `roof` |
| `shape` | `box`, `cylinder`, `arch` or `roof` (anything else is rejected) |
| `color` | `red`, `blue`, `green`, `yellow`, `orange`, `purple`, `natural` |
| `quantity` | how many we own (0 or more) |
| `width_cm`, `depth_cm`, `height_cm` | block size as it stands (width left-right, depth front-back) |

`(type_id, color)` is unique. Empty rows are spare space to fill in.

## Look at the data

Dashboard: open the link above, then the `block_inventory` table.

Or run in the dashboard's SQL editor:

```sql
-- everything filled in
select * from block_inventory where type_id is not null and type_id <> '' order by id;

-- total blocks per color
select color, sum(quantity) from block_inventory group by color order by color;

-- total blocks per type
select type_id, sum(quantity) from block_inventory group by type_id order by type_id;
```

## Edit the data

Click a cell in the dashboard table, or:

```sql
update block_inventory set quantity = 3 where type_id = 'cube' and color = 'red';
```

## From code or Claude Code

- Row-level security is on with no policies, so the public (anon) API key **cannot** read or write. Use the dashboard, or a server-side key kept out of git.
- In Claude Code, the Supabase connector can run SQL on project `ykevkqzxuthubvbqkcld`.

## Known mismatches

- Plank is 3 x 1.4 x 7 here (standing) but 7 x 3 x 1.4 in `catalog.py`.
- Colors and counts here (e.g. `natural`, `purple`, `yellow` blocks) are not all in `catalog.py` yet.
