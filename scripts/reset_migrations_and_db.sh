dropdb djangit-exmaple
createdb djangit-exmaple
rm -rf examples/migrations
./manage.py makemigrations examples
./manage.py migrate examples