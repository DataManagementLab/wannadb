## File Structure

```
.
├── entrypoint.sh
├── util.py
├── __init__.py
├── .env
│   └── .dev
├── Postgres
│   ├── queries.py
│   ├── transactions.py
│   ├── util.py
│   └── __init__.py
├── Redis
│   ├── RedisCache.py
│   ├── util.py
│   └── __init__.py
├── routing
│   ├── core.py
│   ├── dev.py
│   ├── files.py
│   ├── user.py
│   └── __init__.py
├── SQLite
│   ├── Cache_DB.py
│   ├── util.py
│   └── __init__.py
└── worker
    ├── data.py
    ├── tasks.py
    ├── util.py
    ├── Web_API.py
    └── __init__.py
```

### Web Root Directory

```
├── entrypoint.sh
├── util.py
├── __init__.py
└── .env
   └── .dev
```
this contains the entrypoint for the webserver, a utility file for general functionality for the whole project,
and a .env file for environment configuration.
a .prod should be added for production environment configuration if tis is needed.
for these changes needs also be done in the Dockerfile

### Postgres
```
Postgres
├── queries.py
├── transactions.py
├── util.py
└── __init__.py
```
Directory related to PostgresSQL database functionality.
This is an abstraction layer for the database connection and queries.

### Redis
```
Redis
├── RedisCache.py
├── util.py
└── __init__.py
```
Directory related to Redis cache functionality.
This is an abstraction layer for the Redis cache. 
It also scopes the cache to a specific namespace for the users.

### Routing
```
routing
├── core.py
├── dev.py
├── files.py
├── user.py
└── __init__.py
```
Directory related to routing functionality for the flask webserver.
- core.py: contains the routes for the main application routes.
- dev.py: contains the routes for developers.
- files.py: contains the routes for file uploads and downloads.
- user.py: contains the routes for user authentication and management.


### SQLite
```
SQLite
│   ├── Cache_DB.py
│   ├── util.py
│   └── __init__.py
```
Directory related to SQLite database functionality.
This is an abstraction layer for the database connection and queries.
It also scopes the DB to a specific namespace for the users.


### Worker
```
worker
    ├── data.py
    ├── tasks.py
    ├── util.py
    ├── Web_API.py
    └── __init__.py
```
Directory related to worker functionality, background tasks and asynchronous processing.
- data.py: contains all altert or new types.
- tasks.py: contains all the tasks that are to be run in the background.
- util.py: contains utility functions for the worker.
- Web_API.py: contains the API for the worker to communicate with the core.
