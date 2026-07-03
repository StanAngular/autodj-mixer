#!/usr/bin/env python3
from smart_mixer import mix_tracks

tracks = [
    ('Korolova - Traces', 'E-Kr00Rz5Ss.wav', 'E-Kr00Rz5Ss.txt'),
    ('Korolova - Me And You', 'bAGbhJHw7iI.wav', 'bAGbhJHw7iI.txt'),
    ('Xenia Torino - Rabbit Hole', 'SxsuQejFeQ4.wav', 'SxsuQejFeQ4.txt'),
    ('Krismi - Unity', 'cV9sji2-jSU.wav', 'cV9sji2-jSU.txt'),
    ('Miss Monique - Look At You', '1DcLu0FO4Js.wav', '1DcLu0FO4Js.txt'),
    ('Xenia Torino - Feeling', '0gQTV1_1u0c.wav', '0gQTV1_1u0c.txt'),
    ('Miss Monique - Hot Sauce', 'WQ-1B0HnhmQ.wav', 'WQ-1B0HnhmQ.txt'),
    ('ARTBAT - Break The Loop', 'ahW0Sd2GOyc.wav', 'ahW0Sd2GOyc.txt'),
    ('Korolova - Shining', 'LVpislPpXuw.wav', 'LVpislPpXuw.txt'),
    ('Miss Monique - Subterranean', 'DCEoPd40fGc.wav', 'DCEoPd40fGc.txt'),
    ('Korolova - My Mind', 'JSXJnjUbjZ0.wav', 'JSXJnjUbjZ0.txt'),
    ('Miss Monique - Electric', 'is3VYANNyDs.wav', 'is3VYANNyDs.txt'),
    ('Korolova & Zamna - Universe', '3nPoogXacBQ.wav', '3nPoogXacBQ.txt'),
    ('Korolova - Another Life', 'SCja2R7xU-k.wav', 'SCja2R7xU-k.txt'),
    ('Miss Monique - Million Miles Away', 'pi9t1g6ysaA.wav', 'pi9t1g6ysaA.txt'),
    ('Miss Monique - Nomacita', 'je0OXc_cQcA.wav', 'je0OXc_cQcA.txt'),
    ('Cherry (UA) - Silent', 'T7Gbd0PU5WE.wav', 'T7Gbd0PU5WE.txt'),
    ("Mary's Land - Breath", '-t99ib1awO4.wav', '-t99ib1awO4.txt'),
    ('Sagan - In Too Deep', 'A972PpbSemY.wav', 'A972PpbSemY.txt'),
    ('Miss Monique - Rajada', 'RVSxHCjSjXc.wav', 'RVSxHCjSjXc.txt'),
    ('Sagan - Takes Me Higher', 'IErKPhAkYFU.wav', 'IErKPhAkYFU.txt'),
]

output = 'MIX-3_Ukrainian_Tech_House_v16.6_2026-06-12.mp3'
print(f'Starting mix: {output}')
print(f'Tracks: {len(tracks)}')
print(f'Mode: a1f_fast (20/21 with A1F JSON)')
print()

mix_tracks(tracks, 'shared/tracks', 'shared/ann', output,
           style='Ukrainian Tech House', author='Hermes',
           cf_bars='auto', analysis_mode='a1f_fast')