# Routes _wannadbBackend_

The Flask app is running by default on port 8000. Here we assume that the app is running on localhost.

---

-   [HelloWorld](#helloworld)
-   [Register](#register)
-   [Login](#login)
-   [Upload Files](#upload-files)
-   [Create Tables (Development)](#create-tables)

---

## HelloWorld

**GET**

```
http://localhost:8000/
```

---

## Register

**POST**

Register a new user.

```
http://localhost:8000/register
```

### Body

```json
{
    "username": "username",
    "password": "password"
}
```

### Response

-   422 : User register **failed**:
    ```json
    {
        "message": "User register failed"
    }
    ```
-   201: User register **success**:
    ```json
    {
        "message": "User registered successfully",
        "token": "eyJhbGciOiJIUI1NiIsIn5cCI6IkpXVCJ9.ey1c2VyIjocGhpbEiLCJpZCIM30.v_lKLd0X-PABkRFXHZa..."
    }
    ```

---

## Login

**POST**

Login as user

```
http://localhost:8000/login
```

### Body

```json
{
    "username": "username",
    "password": "password"
}
```

### Response

-   401: User login **failed**:
    ```json
    {
        "message": "Wrong Password"
    }
    ```
-   200: User login **success**:
    ```json
    {
        "message": "Log in successfully",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1..."
    }
    ```
    
---

## Organisation

**POST**

creatOrganisation

```
http://localhost:8000/creatOrganisation
```

### Body

```json
{
    "authorization": "---",
    "organisationName": "---"
}
```

### Response

-   409: duplication **Conflict**:
    ```json
    {
    "error": "name already exists."
    }
    ```
-   200: **success**:
    ```json
    {
    "organisation_id": "---"
    }
    ```

---

## Upload Files

**POST**

Upload files.

```
http://localhost:8000/data/upload
```

### Body

-   `file` (form-data): Files to upload
-   `authorization` (form-data): User authorization token
-   `organisationId` (form-data): Organization ID

### Response

-   400: Upload **failed**:
    ```
    Returns a list of document file types.
    ```
-   207: Upload **partial success**:
    ```
    Returns a list of document file types and documentIds.
    ```
-   201: Upload **success**:
    ```
    Returns a list of documentIds.
    ```

## Get Dokument

**POST**

get file.

```
http://localhost:8000/dev/getDocument/<_id>
```

### Body

-   None

### Response

-   String of File Content


---

## create-tables

**POST**

Create tables (Development).

```
http://localhost:8000/create-tables
```
