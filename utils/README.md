## Set Up
In case of proper running, program has to be launched from `utils` directory, e.g

```bash
cd utils
```
List of commands is available under the `help`
```bash
python make_locale.py --help
```

## Prepare new csv to translation
Below command extracts text to translation from `py` files and saves it into `csv` file.
```bash
python make_locale.py create-csv --new <csv-file-name>
```
e.g
```bash
python make_locale.py create-csv --new temp_csv_file.csv
```

## Prepare diff csv to translation
Below command makes a `csv` file based on reference `po` file, which has already been translated.
```bash
python make_locale.py create-csv --diff=<reference-po-file> <csv-file-name>
```
e.g
```bash
python make_locale.py create-csv --diff=../electrum/locale/es_ES/electrum.po temp_csv_file.csv
```

## Compile po from csv
Below command compiles translated data from `csv` into corresponding `po` and `mo` files.

|:warning: Warning: Csv file header has to contain proper language abbreviation, otherwise translations will be invisible. EV supports following language abbreviations `en_UK,ko_KR,ja_JP,zh_CN,vi_VN,es_ES,pt_PT,id_ID,tr_TR`|
|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

```bash
python make_locale.py compile-po <csv-file>
```
e.g
```bash 
python make_locale.py compile-po <csv-file>
```
For more options look in `help`
```bash
python make_locale.py compile-po --help
```

## Extract copy to csv
Below command extracts data from all found `po` files and put them into single `csv` file.
```bash
python extract_copy_to_csv.py <csv-file>
```
e.g
```bash
python extract_copy_to_csv.py copy.csv
```
Look into `python extract_copy_to_csv.py --help` as well.
