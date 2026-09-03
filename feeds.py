# Список источников под тему backend + Java.
# Можно свободно добавлять/удалять строки — главное, валидный RSS/Atom URL.
# Часть источников (dev.to, stackoverflow.blog, reddit r/programming) шире,
# чем чисто Java — они оставлены для объёма кандидатов, а фильтрует по теме
# уже сама модель на этапе отбора (см. TOPIC_FOCUS в main.py).

FEEDS = [
    # Java / JVM — специализированные
    "https://inside.java/feed.xml",              # официальный блог OpenJDK/Java
    "https://spring.io/blog.atom",                # Spring Framework
    "https://www.baeldung.com/feed",               # практические Java/Spring статьи
    "https://in.relation.to/feed.xml",             # Hibernate / Red Hat
    "https://quarkus.io/feed.xml",                 # Quarkus (Java backend-фреймворк)
    "https://www.reddit.com/r/java/.rss",
    "https://go.dev/blog/feed.atom",               # официальный блог Go
    "https://www.reddit.com/r/golang/.rss",

    # Backend-инженерия в целом (архитектура, бэкенд-практики)
    "https://martinfowler.com/feed.atom",
    "https://netflixtechblog.com/feed",
    "https://aws.amazon.com/blogs/aws/feed/",

    # Более широкие источники — оставлены для объёма, модель отфильтрует нерелевантное
    "https://www.infoq.com/feed",
    "https://dev.to/feed",
    "https://stackoverflow.blog/feed/",
    "https://www.reddit.com/r/programming/.rss",
]
