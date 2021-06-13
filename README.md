# ac-overlvlitems
Finds overlevelled and underlevelled item drops in AzerothCore's reference loot tables and generates SQL to delete them.

## Requirements ##
Requires a file called "db-auth.txt" in the program directory. This contains authorization details for the MySQL database. 
This file simply contains the DB username on the first line, and the DB password on the second line. 

## How It Works ##
Criteria for finding overlevelled items:
- Creatures:
  - must be normal non-elites.
  - must be in the open Classic world (Eastern Kingdoms or Kalimdor). Raid and dungeon mobs are not checked.
  
- Items: 
  - must be 4 or more levels higher than the creature that drops it.
  - must not start a quest.
  - must be either armour or a weapon.
  - must be common (white) quality or better.
  - must be equippable.
  - cannot be a shirt or tabard.
