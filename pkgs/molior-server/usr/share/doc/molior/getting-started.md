# Getting Started

## 1. Add a molior.yml to your repository

```sh
$ cd <myrepository>
$ cat <<EOF > debian/molior.yml
config_version: '1'
targets:
  myproject:
    - '1'
EOF
```

## 2. Create a release using the create-release script

Please install the molior-tools package.

Once the package is installed you can use the create-release command to create releases:
```sh
$ cd <myrepo>
$ create-release
```

## 3. Add your repository to the desired project/version on molior

Once the previous steps are done add your repository to the desired project/version on molior. Make sure this project/version matches the one(s) specified in your `molior.yml`.

## 4. Setup hooks to trigger builds

You can configure your git server to notify molior about new commits.

Configure a post-receive hook with the following parameters:
* Method: POST
* URL: http://moliorserver/api/build
* Body: {"repository": "$REPO", "git_ref": "$GIT_REF", "git_branch": "$GIT_BRANCH"}

Note:
* repository is the git URL as registered in molior
* git_ref is optional, latest version tag will be built when omitted
* git_branch is optional and only displayed in the Web UI

## Build notifications

Molior provides build hooks for integration into existing build pipelines. These web hooks can be configured per sourcerepository.

The following http methods are supported:

- GET
- POST
- PUT

If `PUT` or `POST` is selected an additional json body can be sent with custom variables. The variables can also be used in the url string, for example: `http://testserver/test/{{repository.name}}`

Here's an example of all available variables:
```json
{
	"name": "{{repository.name}}",
	"project": {
		"name": "{{project.name}}",
		"version": "{{project.version}}"
	},
	"build": {
		"url": "{{build.url}}",
		"raw_log_url": "{{build.raw_log_url}}",
		"version": "{{build.version}}",
		"status": "{{build.status}}",
		"maintainer": {
			"email": "{{maintainer.email}}"
		},
		"scm": {
			"url": "{{repository.url}}",
			"branch": "{{build.branch}}",
			"commit": "{{build.commit}}"
		},
		"platform": {
			"distrelease": "{{platform.distrelease}}",
			"version": "{{platform.version}}",
			"architecture": "{{platform.architecture}}"
		}
	}
}
```

If you are using `GET` be aware that you may have to **urlencode** your variables like in order for the request to be correct: `http://testserver/test/{{build.version|urlencode}}`

Filled with data:
```json
{
	"name": "hooks-test",
	"project": {
		"name": "test",
		"version": "1"
	},
	"build": {
		"url": "http://moliorserver/#!/build/21817",
		"raw_log_url": "http://moliorserver/buildout/21817/build.log",
		"version": "2.1.3+git20180209104717-71dbdc3",
		"status": "successful",
		"maintainer": {
			"email": "maintainer@molior.info"
		},
		"scm": {
			"url": "ssh://git@gitserver/hooks-test.git",
			"branch": "master",
			"commit": "71dbdc30108474a7b283998579dff8f0bcde3b5a"
		},
		"platform": {
			"architecture": "all",
			"distrelease": "jessie",
			"version": "8.9"
		}
	}
}
```

If you want to send notifications to bitbucket you can use the following `POST` hook:

`https://ciserver/api/{{build.commit|urlencode}}`

Filled with data:

```json
{
    "key":"molior-{{platform.distrelease}}-{{platform.version}}-{{platform.architecture}}-{{project.name}}-{{project.version}}",
    "name":"Molior {{platform.architecture}} / {{platform.version}} / {{platform.distrelease}} Build for {{build.commit}}",
    {% if build.status == "building" %}
    "state":"INPROGRESS",
    {% elif build.status == "successful" %}
    "state":"SUCCESSFUL",
    {% else %}
    "state":"FAILED",
    {% endif %}
    "description":"{{build.status}}",
    "url":"{{build.url}}"
}
```
