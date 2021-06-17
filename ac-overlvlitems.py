# Find NPCs dropping overlevelled items by examining reference_loot_templates
# and generate SQL to delete RLT references from creature templates in DB.

# Map check ensures only mobs tracked are in open world (Eastern Kingdoms
# and Kalimdor.) Note this means dungeon/instance and raid mobs are not
# checked. Mobs must also be non-elite.
# Todo - rewrite to also find underlevelled items
#      - improve SQL speed, it's too slow atm

from mysql.connector import connect, Error
from os import path
import sys
import time

def open_sql_db(db_user, db_pass):
    try:
        db = connect(host = 'localhost',
                     database = 'acore_world',
                     user = db_user,
                     password = db_pass)
        if db.is_connected():
            print('Connected to AzCore database.')
    except Error as e:
        print(e)
        sys.exit(1)

    return db, db.cursor()

def get_auth_details(infile):
	filepath = path.dirname(path.abspath(__file__))
	try:
		with open(path.join(filepath, infile), 'r') as authfile:
			auth = [x.strip() for x in authfile.readlines()]
		return auth[0], auth[1]
	except Exception as err:
		print(err)
		sys.exit(1)

def process_data(found, gen_sql):
    oli = {}
    output, sqlout = [], []
    for item in found:
        npc_id, reftable = item[0], item[4]
        if npc_id not in oli or reftable not in oli[npc_id]:
            oli[npc_id] = {reftable: 1}
        else:
            oli[npc_id][reftable] += 1

    for item in found:
        npc_id, reftable = item[0], item[4]
        if npc_id in oli and reftable in oli[npc_id]:
            numfound = oli[npc_id][reftable]
            output.append(f'ID: {npc_id}, {item[1]}, lvl {item[3]} -> '\
                          f'CLT {item[9]} -> '\
                          f'RLT {reftable} -> Item ID: {item[5]}, '\
                          f'lvl {item[7]} {item[6]}')
            if numfound > 1:
                output.append(f' and {numfound-1} others\n')
            else:
                output.append('\n')

            if gen_sql:
                sqlout.append(f'-- Deletes RLT {reftable} from lvl {item[2]} '\
                              f'{item[1]}, ID {npc_id} ({numfound} '\
                              f'items/{item[8]} level gap)\n')
                sqlout.append(f'DELETE FROM `creature_loot_template` WHERE '\
                              f'`Entry` = {item[9]} AND `Reference` = {reftable};\n\n')
            del oli[npc_id][reftable]

    return ''.join(output), ''.join(sqlout)

def export_data(found, levelstr, level_diff, gen_sql=True):
    outstr, sqlout = process_data(found, gen_sql)
    outfilename = f'ac-{"over" if level_diff >= 0 else "under"}level-{levelstr}.txt'
    with open(outfilename, 'w') as outfile:
        outfile.write(outstr)
    print(f'Data written to file {outfilename}.')

    if sqlout != []:
        sqloutfilename = outfilename[:-4] + '-sql.txt'
        with open(sqloutfilename, 'w') as sqloutfile:
            sqloutfile.write(sqlout)
        print(f'SQL commands written to {sqloutfilename}.')

def build_rlt_table(db, cursor):
	# finds all RLTs containing other RLTs
    rlts, unrolled = {}, {}

    query = ('SELECT rlt.entry, rlt.reference '
             'FROM `reference_loot_template` rlt '
             'WHERE rlt.reference != 0')
    cursor.execute(query)
    for rlt in cursor.fetchall():
        k, v = rlt
        rlts[k] = rlts.get(k, []) + [v]

    for k, v in rlts.items():
        queue = set(v)
        while queue:
            link = queue.pop()
            if link in rlts:
                for l in rlts[link]:
                    queue.add(l)
                if link not in v:
                    v.append(link)
        unrolled[k] = list(set(v))
    return unrolled

def get_rlt_table(db, cursor, rlt_id):
    # returns all items in a specified RLT that meet query criteria
    items = []
    #print(f'Reading RLT {rlt_id}.')

    query = ('SELECT it.entry, it.name, it.ItemLevel '
             'FROM `reference_loot_template` rlt '
             'JOIN `item_template` it ON rlt.item = it.entry '
             'WHERE it.startquest = 0 AND it.class IN (2, 4) '
             'AND rlt.reference = 0 AND it.Quality > 0 '
             'AND it.inventorytype NOT IN (0, 4, 19, 20, 23) '
            f'AND rlt.entry = {rlt_id}')
    cursor.execute(query)
    for item in cursor.fetchall():
        it_entry, it_name, it_itemlevel = item
        items.append(item)

    return {rlt_id: items}

def scan_reftables(min_npc_level=1, max_npc_level=58, leveldiff=4):
    found = []
    npcs, rlt_tables = {}, {}

    db_user, db_pass = get_auth_details('db-auth.txt')
    db, cursor = open_sql_db(db_user, db_pass)

    rlts = build_rlt_table(db, cursor)

    query = ('SELECT DISTINCT ct.entry, ct.name, ct.minlevel, ct.maxlevel, '
             'clt.entry, rlt.entry '
             'FROM `creature_template` ct '
             'JOIN `creature_loot_template` clt ON ct.lootid = clt.entry '
             'JOIN `reference_loot_template` rlt ON clt.reference = rlt.entry '
             'AND clt.reference != 0 AND ct.rank = 0 '
            f'AND ct.minlevel >= {min_npc_level} '
            f'AND ct.maxlevel <= {max_npc_level} '
             'AND ct.entry IN (SELECT ct.entry FROM `creature_template` ct ' 
                              'JOIN `creature` c ON c.id = ct.entry '
                              'WHERE c.map IN (0, 1))')      
    cursor.execute(query)
    npclist = cursor.fetchall()
    listsize = len(npclist)
    
    # build NPC -> NPC info + RLT IDs lookup table
    for count, npc in enumerate(npclist):
        #print(f'Scanning {npc[1]}')
        new_id = npc[0]
        if new_id not in npcs:
            npcs[new_id] = [npc[x] for x in range(1, 6)]
        else:
            npcs[new_id].append(npc[5])

    for npc_id, npcdata in npcs.items():
        npc_name, npc_minlvl, npc_maxlvl, npc_lootid, *curr_rlts = npcdata
        
        #add nested RLTs
        addlist = []
        for x in curr_rlts:
            if x in rlts:
                addlist += rlts[x]
        curr_rlts = list(set(curr_rlts + addlist))

        for rlt_id in curr_rlts:
            if rlt_id not in rlt_tables: #cache RLT
                rlt_tables.update(get_rlt_table(db, cursor, rlt_id))

            for item in rlt_tables[rlt_id]:
                if leveldiff >= 0 and item[2] >= npc_maxlvl + leveldiff:
                    new = [npc_id, npc_name, npc_minlvl, npc_maxlvl, rlt_id,
                               item[0], item[1], item[2], item[2] - npc_maxlvl,
                               npc_lootid]
                    found.append(new)
                elif leveldiff < 0 and item[2] <= npc_minlvl + leveldiff:
                    new = [npc_id, npc_name, npc_minlvl, npc_maxlvl, rlt_id,
                               item[0], item[1], item[2], npc_minlvl - item[2],
                               npc_lootid]
                    found.append(new)

    # sort by level diff
    found.sort(key = lambda x: x[8], reverse=True)
    return found

def batch_scan_lvl_ranges(level_diff):
	# allows scans of defined level ranges all at once
	ranges  = [[1, 19], [20, 29], [30, 39], [40, 49], [50, 58], [1, 58]]
	for min_lvl, max_lvl in ranges:
		found = scan_reftables(min_lvl, max_lvl, level_diff)
		export_data(found, f'{min_lvl}-{max_lvl}', level_diff, gen_sql=True)

def main():
	start = time.time()
	min_lvl, max_lvl = 1, 58 # level ranges are inclusive, so min <= val <= max
	level_diff = 4 #positive number for overlevelled, negative for underlevelled
	#batch_scan_lvl_ranges(level_diff)

	found = scan_reftables(min_lvl, max_lvl, level_diff)
	export_data(found, f'{min_lvl}-{max_lvl}', level_diff, gen_sql=True)

	print(f'Run complete in {time.time() - start:.2f} secs.')

if __name__ == '__main__':
    main()
