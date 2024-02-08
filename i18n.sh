# See https://phrase.com/blog/posts/i18n-advantages-babel-python/

echo "Extract"
pybabel extract *.py -o locale/base.pot


echo "Init translation files"
#pybabel init -l fr_FR en_US -i locale/base.pot -d locale
#pybabel init -l en_US -i locale/base.pot -d locale

echo "update from edited pot file"
pybabel update -i locale/base.pot -d locale

echo "Do translation (waiting til you hit enter key)"
read

echo "compile"
pybabel compile -d locale
