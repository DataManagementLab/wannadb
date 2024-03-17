# Routes _wannadbBackend_

The Flask app is running by default on port 8000. Here we assume that the app is running on localhost.

---


-   [User Routes](#User-Routes)
-   [File Routes](#File-Routes)
-   [Core Routes](#Core-routes)


---
## User Routes

-   [Register a new user](#register-a-new-user)
-  [Login as a user](#login-as-a-user)
-  [Delete a user](#delete-a-user)
- [Create an organization](#create-an-organization)
- [Leave an organization](#leave-an-organization)
- [Get organizations for a user](#get-organizations-for-a-user)
- [Get organization name by ID](#get-organization-name-by-id)
- [Get organization names for a user](#get-organization-names-for-a-user)
- [Add a user to an organization](#add-a-user-to-an-organization)
- [Get members of an organization](#get-members-of-an-organization)
- [Get user name suggestions](#get-user-name-suggestions)

### Register a new user.

```
http://localhost:8000/register
```

-   Body
    ```json
    {
        "username": "username",
        "password": "password"
    }
    ```
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

### Login as a user.

```
http://localhost:8000/login
```
-   Body
    ```json
    {
        "username": "username",
        "password": "password"
    }
    ```
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

### Delete a user.

```
http://localhost:8000/deleteUser/
```
-   Body
    ```json
    {
        "username": "username",
        "password": "password"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   401: User not authorized.
-   401: Wrong Password.
-   204: User deleted successfully.
-   409: User deletion failed.

---

### Create an organization.
```
http://localhost:8000/createOrganisation
```
-   Body
    ```json
    {
        "organisationName": "organisation_name"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Organization created successfully.
-   409: Organization creation failed.

---

### Leave an organization.

```
http://localhost:8000/leaveOrganisation
```
-   Body
    ```json
    {
        "organisationId": "organisation_id"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: User left the organization successfully.
-   500: Error leaving organization.

---

### Get organizations for a user.
```
http://localhost:8000/getOrganisations
```
-   Body
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Retrieved user's organizations successfully.
    ```json
    {
        "organisation_ids": ["number"]
    }
    ```
-   404: User is not in any organization.
-   409: Error retrieving organizations.

---

### Get organization name by ID.
```
http://localhost:8000/getOrganisationName/<_id>
```
-   URL
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Body
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Retrieved organization name successfully.
    ```json
    {
        "organisation_name": ["string"]
    }
    ```
-   404: Organization not found.
-   409: Error retrieving organization name.

---

### Get organization names for a user.

```
http://localhost:8000/getOrganisationNames
```

-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Retrieved user's organization names successfully.
    ```json
    {
        "organisations": ["number"]
    }
    ```
-   404: User is not in any organization.
-   409: Error retrieving organization names.

---

### Add a user to an organization.

```
http://localhost:8000/addUserToOrganisation
```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Body
    ```json
    {
        "organisationId": "organisation_id",
        "newUser": "new_user"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: User added to the organization successfully.
    ```json
    {
        "organisation_id": "number"
    }
    ```
-   409: Error adding user to organization.

---

### Get members of an organization.
```
http://localhost:8000/getOrganisationMembers/<_id>
```
-   URL
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Retrieved organization members successfully.
    ```json
    {
        "members": ["string"]
    }
    ```
-   404: Organization not found.
-   409: Error retrieving organization members.

---

### Get user name suggestions.
```
http://localhost:8000/get/user/suggestion/<_prefix>
```

-   URL
    ```json
    {
        "_prefix": "organisation_id"
    }
    ```
-   401: No authorization provided.
-   400: Invalid authorization token.
-   200: Retrieved username suggestions successfully.
    ```json
    {
        "usernames": ["string"]
    }
    ```

---
## File Routes

-   [Upload File](#upload-file)
-   [Get Files](#get-files)
-   [Get document base for an organization](#get-document-base-for-an-organization)
-   [Update file content](#update-file-content)
-   [Delete a file](#delete-a-file)
-   [Get a file](#get-a-file)
---

### Upload File

```
http://localhost:8000/data/upload/file
```

-   Form
    -   `file`: The file to upload.
    -   `organisationId`: ID of the organization.
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   200: File uploaded successfully.
    ```json
    {
        "document_ids": ["number"]
    }
    ```
-   400: Invalid file type.
    ```json
    {
        "document_ids": ["string"]
    }
    ```
-   207: Multiple files uploaded, some with errors.
    ```json
    {
        "document_ids": ["number|string"]
    }
    ```

---

### Get Files

```
http://localhost:8000/data/organization/get/files/<_id>
```

-   URL
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   200: Retrieved organization files successfully.
    ```json
    {
        "documents": "id"
    }
    ```

---

### Get document base for an organization.

```
http://localhost:8000/data/organization/get/documentbase/<_id>
```

-   URL
    ```json
    {
        "_id": "organisation_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   200: Retrieved document base successfully.
    ```json
    {
        "document_base": "document_base"
    }
    ```

---

### Update file content.

```
http://localhost:8000/data/update/file/content
```

-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Body
    ```json
    {
        "documentId": "document_id",
        "newContent": "new_content"
    }
    ```
-   401: No authorization provided.
-   200: File content updated successfully.
    ```json
    {
        "status": "bool"
    }
    ```

---

### Delete a file.

```
http://localhost:8000/data/file/delete
```

-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   Body
    ```json
    {
        "documentId": "document_id"
    }
    ```
-   401: No authorization provided.
-   200: File deleted successfully.
    ```json
    {
        "status": "bool"
    }
    ```

---

### Get a file.

```
http://localhost:8000/data/get/file/<_id>
```


-   URL
    ```json
    {
        "_id": "document_id"
    }
    ```
-   Header
    ```json
    {
        "authorization": "---authorization---jwt---"
    }
    ```
-   401: No authorization provided.
-   200: Retrieved file successfully.
    ```json
    {
        "document_ids": ["list", "string", "bytes"]
    }
    ```
-   404: File not found.
    ```json
    {
        "document_ids": []
    }
    ```
-   206: Partial content retrieved.
    ```json
    {
        "document_ids": ["list", "string", "bytes"]
    }
    ```

--

## Core Routes

This module defines Flask routes for the 'core' functionality of the Wannadb UI.

- [Create a document base](#create-a-document-base)
- [Load a document base](#load-a-document-base)
- [Interactive document population](#interactive-document-population)
- [Add attributes to a document base](#add-attributes-to-a-document-base)
- [Update the attributes of a document base](#update-the-attributes-of-a-document-base)
- [Sort nuggets](#sort-nuggets)
- [Confirm a custom nugget](#confirm-a-custom-nugget)
- [Confirm a match nugget](#confirm-a-match-nugget)
- [Get document base for an organization](#get-document-base-for-an-organization)
 

---

### Create a document base

```
http://localhost:8000/core/create_document_base
```

-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `document_ids`: Comma-separated list of document IDs.
    -   `attributes`: Comma-separated list of attributes.
-   401: No authorization provided.
-   200: Document base created successfully.
    ```json
    {"task_id": "task_id"}
    ```

---

### Load a document base.

```
http://localhost:8000/core/document_base/load
```


-   Form
-   `authorization`: Your authorization token.
-   `organisationId`: Your organization ID.
-   `baseName`: Your document base name.
-   401: No authorization provided.
-   200: Document base loaded successfully.
    ```json
    {"task_id": "task_id"}
    ```

---

### Interactive document population.


```
http://localhost:8000/core/document_base/interactive
```

-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
-   401: No authorization provided.
-   200: Document base populated interactively.
    ```json
    {"task_id": "task_id"}
    ```

---

### Add attributes to a document base.

```
http://localhost:8000/core/document_base/attributes/add
```


-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `attributes`: Comma-separated list of attributes.
-   401: No authorization provided.
-   200: Attributes added to document base successfully.
    ```json
    {"task_id": "task_id"}
    ```

---

### Update the attributes of a document base.

```
http://localhost:8000/core/document_base/attributes/update
```


-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `attributes`: Comma-separated list of attributes.
-   401: No authorization provided.
-   200: Attributes updated successfully.
    ```json
    {"task_id": "task_id"}
    ```

---

### Sort nuggets.

```
http://localhost:8000/core/document_base/order/nugget
```

-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `documentName`: Your document name.
    -   `documentContent`: Your document content.
-   401: No authorization provided.
-   200: Nuggets sorted successfully.
    ```json
    {"task_id": "task_id"}
    ```

---

### Confirm a custom nugget.

```
http://localhost:8000/core/document_base/confirm/nugget/custom
```

-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `documentName`: Your document name.
    -   `documentContent`: Your document content.
    -   `nuggetText`: Nugget as text.
    -   `startIndex`: Start index of the nugget.
    -   `endIndex`: End index of the nugget.
    -   `interactiveCallTaskId`: Interactive call task ID.
-   401: No authorization provided.
-   200: Nugget confirmed successfully.
    ```json
    {"task_id": "task_id"}
    ```

---

### Confirm a match nugget.

```
http://localhost:8000/core/document_base/confirm/nugget/match
```

-   Form
    -   `authorization`: Your authorization token.
    -   `organisationId`: Your organization ID.
    -   `baseName`: Your document base name.
    -   `documentName`: Your document name.
    -   `documentContent`: Your document content.
    -   `nuggetText`: Nugget as text.
    -   `startIndex`: Start index of the nugget.
    -   `endIndex`: End index of the nugget.
    -   `interactiveCallTaskId`: Interactive call task ID.
-   401: No authorization provided.
-   200: Nugget confirmed successfully.
    ```json
    {"task_id": "task_id"}
    ```



