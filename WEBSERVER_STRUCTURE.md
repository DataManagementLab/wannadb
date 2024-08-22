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
This section contains the following files:
- `entrypoint.sh`: This is the entrypoint for the webserver.
- `util.py`: This file provides general functionality for the entire project.
- `__init__.py`: This is an initialization file.
- `.env`: This file is used for environment configuration.
- `.dev`: This file is specific to the development environment.

If a production environment configuration is needed, a `.prod` file should be added. Please make sure to update the Dockerfile accordingly to reflect these changes.

### Postgres
```
Postgres
├── queries.py
├── transactions.py
├── util.py
└── __init__.py
```
Directory related to PostgresSQL database functionality.
This section provides an abstraction layer for the database connection and queries.

### Redis
```
Redis
├── RedisCache.py
├── util.py
└── __init__.py
```
Directory related to Redis cache functionality.
This section provides an abstraction layer for the Redis cache, allowing for efficient caching of data. It also ensures that the cache is scoped to a specific namespace for the users, preventing any conflicts or data leakage.

### Routing
```
routing
├── core.py
├── dev.py
├── files.py
├── user.py
└── __init__.py
```
Directory related to routing functionality for the Flask web server.

- `core.py`: Contains the routes for the main application routes.
- `dev.py`: Contains the routes for developers.
- `files.py`: Contains the routes for file uploads and downloads.
- `user.py`: Contains the routes for user authentication and management.


### SQLite
```
SQLite
│   ├── Cache_DB.py
│   ├── util.py
│   └── __init__.py
```
Directory related to SQLite database functionality.

This section provides an abstraction layer for the database connection and queries. It also ensures that the database is scoped to a specific namespace for the users, improving data organization and security.


### Worker
```
worker
    ├── data.py
    ├── tasks.py
    ├── util.py
    ├── Web_API.py
    └── __init__.py
```
Directory related to worker functionality, background tasks, and asynchronous processing.

- `data.py`: Contains all alert or new types.
- `tasks.py`: Contains all the tasks that are to be run in the background.
- `util.py`: Contains utility functions for the worker.
- `Web_API.py`: Contains the API for the worker to communicate with the core.
