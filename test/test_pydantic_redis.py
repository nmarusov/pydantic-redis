"""Tests for the redis orm"""

from typing import Dict, Any, List, Tuple

import pytest

from pydantic_redis.config import RedisConfig
from pydantic_redis.model import Model
from test.conftest import redis_store_fixture, Book, books, Author, authors, Library, library, BooksToRead, books_to_read, Basket, basket, DVDBox, dvd_box, DVD

def test_redis_config_redis_url():
    password = "password"
    config_with_no_pass = RedisConfig()
    config_with_ssl = RedisConfig(ssl=True)
    config_with_pass = RedisConfig(password=password)
    config_with_pass_ssl = RedisConfig(ssl=True, password=password)

    assert config_with_no_pass.redis_url == "redis://localhost:6379/0"
    assert config_with_ssl.redis_url == "rediss://localhost:6379/0"
    assert config_with_pass.redis_url == f"redis://:{password}@localhost:6379/0"
    assert config_with_pass_ssl.redis_url == f"rediss://:{password}@localhost:6379/0"


def test_register_model_without_primary_key(redis_store):
    """Throws error when a model without the _primary_key_field class variable set is registered"""

    class ModelWithoutPrimaryKey(Model):
        title: str

    with pytest.raises(AttributeError, match=r"_primary_key_field"):
        redis_store.register_model(ModelWithoutPrimaryKey)

    ModelWithoutPrimaryKey._primary_key_field = None

    with pytest.raises(Exception, match=r"should have a _primary_key_field"):
        redis_store.register_model(ModelWithoutPrimaryKey)


def test_store_model(redis_store):
    """Tests the model method in store"""
    assert redis_store.model("Book") == Book

    with pytest.raises(KeyError):
        redis_store.model("Notabook")


@pytest.mark.parametrize("store", redis_store_fixture)
def test_bulk_insert(store):
    """Providing a list of Model instances to the insert method inserts the records in redis"""
    book_keys = [f"book_%&_{book.title}" for book in books]
    keys = book_keys + [f"author_%&_{author.name}" for author in authors.values()]
    store.redis_store.delete(*keys)

    for key in keys:
        item_in_redis = store.redis_store.hgetall(name=key)
        assert item_in_redis == {}

    Book.insert(books)

    with store.redis_store.pipeline() as pipeline:
        for book_key in book_keys:
            pipeline.hgetall(name=book_key)
        books_in_redis = pipeline.execute()
    books_in_redis_as_models = [__deserialize_book_data(book) for book in books_in_redis]
    assert books == books_in_redis_as_models


@pytest.mark.parametrize("store", redis_store_fixture)
def test_bulk_nested_insert(store):
    """Providing a list of Model instances to the insert method also upserts their nested records in redis"""
    book_keys = [f"book_%&_{book.title}" for book in books]
    author_keys = [f"author_%&_{author.name}" for author in authors.values()]
    keys = book_keys + author_keys

    for key in keys:
        item_in_redis = store.redis_store.hgetall(name=key)
        assert item_in_redis == {}

    Book.insert(books)

    with store.redis_store.pipeline() as pipeline:
        for key in author_keys:
            pipeline.hgetall(name=key)
        authors_in_redis = pipeline.execute()
    authors_in_redis_as_models = sorted(
        [Author(**Author.deserialize_partially(author)) for author in authors_in_redis], key=lambda x: x.name)
    expected = sorted(authors.values(), key=lambda x: x.name)
    assert expected == authors_in_redis_as_models


@pytest.mark.parametrize("store", redis_store_fixture)
def test_insert_single(store):
    """
    Providing a single Model instance inserts that record in redis
    """
    key = f"book_%&_{books[0].title}"
    book = store.redis_store.hgetall(name=key)
    assert book == {}

    Book.insert(books[0])

    book = store.redis_store.hgetall(name=key)
    book_as_model = __deserialize_book_data(book)
    assert books[0] == book_as_model


@pytest.mark.parametrize("store", redis_store_fixture)
def test_insert_single_nested(store):
    """
    Providing a single Model instance upserts also any nested model into redis
    """
    key = f"author_%&_{books[0].author.name}"
    author = store.redis_store.hgetall(name=key)
    assert author == {}

    Book.insert(books[0])

    author = store.redis_store.hgetall(name=key)
    author_as_model = Author(**Author.deserialize_partially(author))
    assert books[0].author == author_as_model


@pytest.mark.parametrize("store", redis_store_fixture)
def test_update_nested_list_of_models(store):
    Library.insert(library)
    books = Book.select()
    assert type(books) is list and len(books) == 4

    _library = Library.select()[0]
    assert all(isinstance(x, Book) for x in _library.books)


@pytest.mark.parametrize("store", redis_store_fixture)
def test_update_nested_set_of_models(store):
    BooksToRead.insert(books_to_read)
    books: List[Book] = Book.select()
    assert type(books) is list and len(books) == 3
    assert all(book.author.name == "Charles Dickens" for book in books)

    _books_to_read = BooksToRead.select()[0]
    assert isinstance(_books_to_read.books, set)
    assert len(_books_to_read.books) == 3
    assert all(isinstance(x, Book) for x in _books_to_read.books)


@pytest.mark.parametrize("store", redis_store_fixture)
def test_update_nested_tuple_of_models(store):
    Basket.insert(basket)
    books: List[Book] = Book.select()
    assert type(books) is list and len(books) == 3
    _basket = Basket.select()[0]
    assert isinstance(_basket.books, tuple)
    assert len(_basket.books) == 3
    assert all(isinstance(x, Book) for x in _basket.books)

@pytest.mark.parametrize("store", redis_store_fixture)
def test_update_nested_tuple_of_different_models(store):
    DVDBox.insert(dvd_box)
    books: List[Book] = Book.select()
    assert type(books) is list and len(books) == 1
    dvds: List[DVD] = DVD.select()
    assert type(dvds) is list and len(dvds) == 1

    _dvdbox = DVDBox.select()[0]
    assert isinstance(_dvdbox.content, tuple)
    assert len(_dvdbox.content) == 2
    assert isinstance(_dvdbox.content[0], Book)
    assert isinstance(_dvdbox.content[1], DVD)


@pytest.mark.parametrize("store", redis_store_fixture)
def test_select_default(store):
    """Selecting without arguments returns all the book models"""
    Book.insert(books)
    response = Book.select()
    sorted_books = sorted(books, key=lambda x: x.title)
    sorted_response = sorted(response, key=lambda x: x.title)
    assert sorted_books == sorted_response


@pytest.mark.parametrize("store", redis_store_fixture)
def test_select_some_columns(store):
    """
    Selecting some columns returns a list of dictionaries of all books models with only those columns
    """
    Book.insert(books)
    books_dict = {book.title: book for book in books}
    columns = ['title', 'author', 'in_stock']
    response = Book.select(columns=['title', 'author', 'in_stock'])
    response_dict = {book['title']: book for book in response}

    for title, book in books_dict.items():
        book_in_response = response_dict[title]
        assert isinstance(book_in_response, dict)
        assert sorted(book_in_response.keys()) == sorted(columns)

        for column in columns:
            if column == 'author':
                assert book_in_response[column] == getattr(book, column)
            else:
                assert f"{book_in_response[column]}" == f"{getattr(book, column)}"


@pytest.mark.parametrize("store", redis_store_fixture)
def test_select_some_ids(store):
    """
    Selecting some ids returns only those elements with the given ids
    """
    Book.insert(books)
    ids = [book.title for book in books[:2]]
    response = Book.select(ids=ids)
    assert response == books[:2]


@pytest.mark.parametrize("store", redis_store_fixture)
def test_update(store):
    """
    Updating an item of a given primary key updates it in redis
    """
    Book.insert(books)
    title = books[0].title
    new_in_stock = not books[0].in_stock
    new_author = Author(name='John Doe', active_years=(2000, 2009))
    book_key = f"book_%&_{title}"
    new_author_key = f"author_%&_{new_author.name}"
    old_book_data = store.redis_store.hgetall(name=book_key)
    old_book = __deserialize_book_data(old_book_data)
    assert old_book == books[0]
    assert old_book.author != new_author

    Book.update(_id=title, data={"author": new_author, "in_stock": new_in_stock})

    book_data = store.redis_store.hgetall(name=book_key)
    book = __deserialize_book_data(book_data)
    author_data = store.redis_store.hgetall(name=new_author_key)
    author = Author(**Author.deserialize_partially(author_data))
    assert book.author == new_author
    assert author == new_author
    assert book.title == old_book.title
    assert book.in_stock == new_in_stock
    assert book.published_on == old_book.published_on


@pytest.mark.parametrize("store", redis_store_fixture)
def test_update_nested_model(store):
    """
    Updating a nested model, without changing its primary key, also updates it its collection in redis
    """
    Book.insert(books)

    new_in_stock = not books[0].in_stock
    updated_author = Author(**books[0].author.dict())
    updated_author.active_years = (2020, 2045)
    book_key = f"book_%&_{books[0].title}"
    author_key = f"author_%&_{updated_author.name}"

    old_author_data = store.redis_store.hgetall(name=author_key)
    old_author = Author(**Author.deserialize_partially(old_author_data))
    old_book_data = store.redis_store.hgetall(name=book_key)
    old_book = __deserialize_book_data(old_book_data)
    assert old_book == books[0]
    assert old_author == books[0].author
    assert old_author != updated_author

    Book.update(_id=books[0].title, data={"author": updated_author, "in_stock": new_in_stock})

    book_data = store.redis_store.hgetall(name=book_key)
    book = __deserialize_book_data(book_data)
    author_data = store.redis_store.hgetall(name=author_key)
    author = Author(**Author.deserialize_partially(author_data))
    assert book.author == updated_author
    assert author == updated_author
    assert book.title == old_book.title
    assert book.in_stock == new_in_stock
    assert book.published_on == old_book.published_on


@pytest.mark.parametrize("store", redis_store_fixture)
def test_delete_multiple(store):
    """
    Providing a list of ids to the delete function will remove the items from redis,
    but leave the nested models intact
    """
    Book.insert(books)
    books_to_delete = books[:2]
    books_left_in_db = books[2:]

    ids_to_delete = [book.title for book in books_to_delete]
    ids_to_leave_intact = [book.title for book in books_left_in_db]

    keys_to_delete = [f"book_%&_{_id}" for _id in ids_to_delete]
    book_keys_to_leave_intact = [f"book_%&_{_id}" for _id in ids_to_leave_intact]
    author_keys_to_leave_intact = [f"author_%&_{author.name}" for author in authors.values()]

    Book.delete(ids=ids_to_delete)

    for key in keys_to_delete:
        deleted_book_in_redis = store.redis_store.hgetall(name=key)
        assert deleted_book_in_redis == {}

    with store.redis_store.pipeline() as pipeline:
        for key in book_keys_to_leave_intact:
            pipeline.hgetall(name=key)
        books_in_redis = pipeline.execute()
        books_in_redis_as_models = [__deserialize_book_data(book) for book in books_in_redis]
        assert books_left_in_db == books_in_redis_as_models

        for key in author_keys_to_leave_intact:
            pipeline.hgetall(name=key)
        authors_in_redis = pipeline.execute()
        authors_in_redis_as_models = sorted(
            [Author(**Author.deserialize_partially(author)) for author in authors_in_redis], key=lambda x: x.name)
        expected = sorted(authors.values(), key=lambda x: x.name)
        assert expected == authors_in_redis_as_models


def __deserialize_book_data(raw_book_data: Dict[bytes, Any]) -> Book:
    """Deserializes the raw book data returning a book instance"""
    data = Book.deserialize_partially(raw_book_data)
    data["author"] = Author.select(ids=[data["__author"]])[0]
    return Book(**data)
