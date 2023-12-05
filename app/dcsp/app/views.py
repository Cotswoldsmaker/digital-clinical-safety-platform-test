"""Manages the views for the dcsp app

This is part of a Django web server app that is used to create a static site in
mkdocs. It utilises several other functions git, github, env manipulation and 
mkdocs

Functions:
    index
    edit_md
    saved_md
    new_md
    log_hazard
    hazard_comment
    open_hazards
    mkdoc_redirect
    upload_to_github
    std_context
    start_afresh
    custom_404
    custom_405
"""
from django.shortcuts import render, redirect
from django.http import HttpResponse, HttpRequest
from django.contrib import messages
from django.conf import settings

import os
import sys
from fnmatch import fnmatch
from dotenv import find_dotenv, dotenv_values
import shutil
from typing import Any

import app.functions.constants as c
from app.functions.constants import EnvKeys

sys.path.append(c.FUNCTIONS_APP)
from app.functions.env_manipulation import ENVManipulator
from app.functions.mkdocs_control import MkdocsControl
from app.functions.docs_builder import Builder
from app.functions.git_control import GitController


from .forms import (
    InstallationForm,
    TemplateSelectForm,
    PlaceholdersForm,
    MDEditForm,
    MDFileSelect,
    LogHazardForm,
    UploadToGithub,
    HazardCommentForm,
)


def index(request: HttpRequest) -> HttpResponse:
    """Index page, carrying out steps to initialise a static site

    Acting as a single page application, this function undertakes several
    steps to set up the mkdocs static site. The state of the installation is
    stored in an .env file as 'setup_step'. There are 4 steps in the
    installation process (labelled steps None, 1, 2 and 3):

    - None: Initial step for the installation process. No value stored for the
    step_step in the .env file. During this step the user is asked if they want
    a 'stand alone' or an 'integrated' installation.
        - Stand alone: this setup is very the DCSP app is only used for hazard
          documentation, with no source code integration. Basically the version
          control is managed by the DCSP app.
        - Integrated: the DCSP is integrated into an already version controlled
          source base, for example along side already written source code.
    - 1: In this step the user is asked to chose a template for the static
         website.
    - 2: In this step the user is asked to enter values for placeholders for the
         static site.
    - 3: The static site is now built and mkdocs has been started and the site
         should be visible.

    Args:
        request (HttpRequest): request from user
    Returns:
        HttpResponse: for loading the correct webpage
    """
    context: dict[str, Any] = {}
    placeholders: dict[str, str] = {}
    setup_step: str | None = None
    template_choice: str = ""
    # form

    if not (request.method == "POST" or request.method == "GET"):
        return render(request, "405.html", std_context(), status=405)

    em = ENVManipulator(settings.ENV_LOCATION)
    setup_step = em.read("setup_step")

    if not setup_step:
        if request.method == "GET":
            context = {"form": InstallationForm()}

            return render(
                request, "installation_method.html", context | std_context()
            )

        elif request.method == "POST":
            form = InstallationForm(request.POST)
            # TODO #27 - check condentials
            if form.is_valid():
                env_m = ENVManipulator(settings.ENV_LOCATION)
                env_m.add(
                    EnvKeys.GITHUB_USERNAME.value,
                    form.cleaned_data["github_username_SA"],
                )
                env_m.add(
                    EnvKeys.EMAIL.value,
                    form.cleaned_data["email_SA"],
                )
                env_m.add(
                    EnvKeys.GITHUB_ORGANISATION.value,
                    form.cleaned_data["github_organisation_SA"],
                )
                env_m.add(
                    EnvKeys.GITHUB_REPO.value,
                    form.cleaned_data["github_repo_SA"],
                )
                env_m.add(
                    EnvKeys.GITHUB_TOKEN.value,
                    form.cleaned_data["github_token_SA"],
                )
                env_m.add("setup_step", "1")

                messages.success(request, "Initialisation selections stored")

                context = {"form": TemplateSelectForm()}

                return render(
                    request, "template_select.html", context | std_context()
                )
            else:
                context = {"form": form}

                return render(
                    request,
                    "installation_method.html",
                    context | std_context(),
                )

    elif setup_step == "1":
        if request.method == "GET":
            context = {"form": TemplateSelectForm()}

            return render(
                request, "template_select.html", context | std_context()
            )

        elif request.method == "POST":
            form = TemplateSelectForm(request.POST)  # type: ignore[assignment]
            if form.is_valid():
                env_m = ENVManipulator(settings.ENV_LOCATION)
                env_m.add("setup_step", "2")
                template_choice = form.cleaned_data["template_choice"]

                doc_build = Builder(settings.MKDOCS_LOCATION)
                doc_build.copy_templates(template_choice)

                messages.success(
                    request,
                    f"{ template_choice } template initiated",
                )

                context = {"form": PlaceholdersForm()}

                return render(
                    request, "placeholders_show.html", context | std_context()
                )
            else:
                context = {"form": form}

                return render(
                    request, "template_select.html", context | std_context()
                )

    elif setup_step == "2" or setup_step == "3":
        if request.method == "GET":
            context = {"form": PlaceholdersForm()}

            return render(
                request, "placeholders_show.html", context | std_context()
            )

        elif request.method == "POST":
            form = PlaceholdersForm(data=request.POST)  # type: ignore[assignment]
            if form.is_valid():
                env_m = ENVManipulator(settings.ENV_LOCATION)
                env_m.add("setup_step", "3")

                doc_build = Builder(settings.MKDOCS_LOCATION)
                placeholders = doc_build.get_placeholders()

                for p in placeholders:
                    placeholders[p] = form.cleaned_data[p]

                doc_build.save_placeholders(placeholders)

                messages.success(
                    request,
                    "Placeholders saved",
                )

                mkdocs = MkdocsControl()
                if not mkdocs.start(wait=True):
                    return render(request, "500.html")

                return render(
                    request, "placeholders_saved.html", context | std_context()
                )
            else:
                context = {"form": form}

                return render(
                    request, "placeholders_show.html", context | std_context()
                )

    # Should never really get here, but added for mypy
    return render(request, "500.html", std_context(), status=500)


def edit_md(request: HttpRequest) -> HttpResponse:
    """Function for editing of markdown files in the static site

    A webpage to allow the user to edit the markdown files used in the
    static site on mkdocs.

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """
    context: dict[str, Any] = {}
    files_md: str = ""
    loop_exit: bool = False
    files: list[str] = []
    name: str = ""
    em: ENVManipulator

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html", status=405)

    em = ENVManipulator(settings.ENV_LOCATION)
    setup_step = em.read("setup_step")

    if setup_step != "2" and setup_step != "3":
        return redirect("/")

    if request.method == "GET":
        if not os.path.isdir(settings.MKDOCS_DOCS_LOCATION):
            return render(request, "500.html", std_context(), status=500)

        # TODO: can we somehow remove p and v here?
        for p, v, files in os.walk(settings.MKDOCS_DOCS_LOCATION):
            for name in files:
                if fnmatch(name, "*.md"):
                    files_md = name
                    loop_exit = True
                    break
            if loop_exit:
                break

    elif request.method == "POST":
        form = MDFileSelect(data=request.POST)
        if form.is_valid():
            files_md = form.cleaned_data["mark_down_file"]
        else:
            context = {"form": form}
            return render(request, "edit_md.html", context | std_context())

    with open(f"{ settings.MKDOCS_DOCS_LOCATION }{ files_md }", "r") as file:
        form_fields = {"text_md": file.read(), "document_name": files_md}

    context = {
        "MDFileSelect": MDFileSelect(initial={"mark_down_file": files_md}),
        "text_md": MDEditForm(initial=form_fields),
        "document_name": files_md,
    }

    return render(request, "edit_md.html", context | std_context())


def saved_md(request: HttpRequest) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """
    context: dict = {}
    text_md_returned: str = ""
    file_md_returned: str = ""
    file_path: str = ""
    em: ENVManipulator

    if request.method == "GET":
        return redirect("/edit_md")

    if not request.method == "POST":
        return render(request, "405.html", std_context(), status=405)

    em = ENVManipulator(settings.ENV_LOCATION)
    setup_step = em.read("setup_step")

    # TODO need to safety return a number from .env or appropriately handle the error
    if int(setup_step) < 2:
        return redirect("/")

    form = MDEditForm(request.POST)
    if form.is_valid():
        file_md_returned = form.cleaned_data["document_name"]
        text_md_returned = form.cleaned_data["text_md"]

        file_path = f"{ settings.MKDOCS_DOCS_LOCATION }{ file_md_returned }"

        if not os.path.isfile(file_path):
            return render(
                request, "500.html", context | std_context(), status=500
            )

        f = open(file_path, "w")
        f.write(text_md_returned)
        f.close()

        messages.success(
            request,
            f'Mark down file "{ file_md_returned }" has been successfully saved',
        )
        context = {
            "MDFileSelect": MDFileSelect(
                initial={"mark_down_file": file_md_returned}
            ),
            "text_md": MDEditForm(initial=request.POST),
            "document_name": file_md_returned,
        }
        return render(request, "edit_md.html", context | std_context())
    else:
        context = {"form": form}
        return render(request, "edit_md.html", context | std_context())

    # For mypy
    return render(request, "500.html", status=500)


def new_md(request: HttpRequest) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html", std_context(), status=405)

    if request.method == "GET":
        context = {"form": LogHazardForm()}
        return render(request, "new_md.html", context | std_context())

    # For mypy
    return render(request, "500.html", status=500)


def log_hazard(request: HttpRequest) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """
    context: dict[str, Any] = {}
    gc: GitController

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html", std_context(), status=405)

    if request.method == "GET":
        context = {"form": LogHazardForm()}
        return render(request, "log_hazard.html", context | std_context())

    if request.method == "POST":
        form = LogHazardForm(request.POST)
        if form.is_valid():
            hazard_title = form.cleaned_data["title"]
            hazard_body = form.cleaned_data["body"]
            hazard_labels = form.cleaned_data["labels"]
            gc = GitController()

            gc.log_hazard(hazard_title, hazard_body, hazard_labels)
            try:
                gc.log_hazard(hazard_title, hazard_body, hazard_labels)
            except Exception as error:
                messages.error(
                    request,
                    f"Error returned from logging hazard - '{ error }'",
                )

                context = {"form": LogHazardForm(initial=request.POST)}

                return render(
                    request, "log_hazard.html", context | std_context()
                )
            else:
                messages.success(
                    request,
                    f"Hazard has been uploaded to GitHub",
                )
                context = {"form": LogHazardForm()}
                return render(
                    request, "log_hazard.html", context | std_context()
                )
        else:
            context = {"form": form}
            return render(request, "log_hazard.html", context | std_context())

    # Should never really get here, but added for mypy
    return render(request, "500.html", std_context(), status=500)


def hazard_comment(request: HttpRequest, hazard_number: "str") -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """

    context: dict[str, Any] = {}
    gc: GitController
    open_hazard: dict = {}

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html", std_context(), status=405)

    if request.method == "GET":
        gc = GitController()
        open_hazards_full = gc.open_hazards()

        for hazard in open_hazards_full:
            if hazard["number"] == int(hazard_number):
                open_hazard = hazard.copy()
                break

        context = {
            "open_hazard": open_hazard,
            "form": HazardCommentForm(
                initial={"comment": c.TEMPLATE_HAZARD_COMMENT}
            ),
            "hazard_number": hazard_number,
        }
        return render(request, "hazard_comment.html", context | std_context())

    if request.method == "POST":
        form = HazardCommentForm(request.POST)
        if form.is_valid():
            comment = form.cleaned_data["comment"]
            gc = GitController()
            # TODO - need error handling here
            gc.add_comment_to_hazard(
                hazard_number=int(hazard_number), comment=comment
            )
            messages.success(
                request,
                f"Hazard '{ hazard_number }' updated.",
            )
            context = {"form": LogHazardForm()}
            return render(
                request, "hazard_comment.html", context | std_context()
            )
        else:
            context = {"form": form}
            return render(
                request, "hazard_comment.html", context | std_context()
            )

    # Should never really get here, but added for mypy
    return render(request, "500.html", std_context(), status=500)


# TODO - testing needed
def open_hazards(request: HttpRequest) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """

    context: dict[str, Any] = {}
    gc: GitController
    open_hazards: list[dict] = []

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html", std_context(), status=405)

    if request.method == "GET":
        # TODO need to check github credentials are valid
        gc = GitController()
        open_hazards = gc.open_hazards()
        context = {"open_hazards": open_hazards}

        return render(request, "open_hazards.html", context | std_context())

    if request.method == "POST":
        return HttpResponse("POST handling not yet built")

    # Should never really get here, but added for mypy
    return render(request, "500.html", std_context(), status=500)


def mkdoc_redirect(request: HttpRequest, path: str) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """

    mkdocs: MkdocsControl

    if not request.method == "GET":
        return render(request, "405.html", std_context(), status=405)

    mkdocs = MkdocsControl()
    mkdocs.start()

    # TODO - need message page for if mkdocs is not running

    if path == "home":
        return redirect(f"http://localhost:9000")
    else:
        return redirect(f"http://localhost:9000/{ path }")

    # Should never really get here, but added for mypy
    return render(request, "500.html", std_context(), status=500)


# TODO - testing needed
def upload_to_github(request: HttpRequest) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """

    context: dict[str, Any] = {}
    gc: GitController

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html", std_context(), status=405)

    if request.method == "GET":
        context = {"form": UploadToGithub()}

        return render(
            request, "upload_to_github.html", context | std_context()
        )

    if request.method == "POST":
        form = UploadToGithub(request.POST)
        if form.is_valid():
            comment = form.cleaned_data["comment"]
            gc = GitController()
            # TODO - need to handle if branch is already up to date
            gc.commit_and_push(comment)
            messages.success(
                request,
                f"Uploaded to Github with a comment of '{ comment }'",
            )
            context = {"form": UploadToGithub()}
            return render(
                request, "upload_to_github.html", context | std_context()
            )

        else:
            context = {"form": form}
            return render(
                request, "upload_to_github.html", context | std_context()
            )

    # Should never really get here, but added for mypy
    return render(request, "500.html", std_context(), status=500)


# -----


def std_context() -> dict[str, Any]:
    """Title

    Description

    Args:
        none

    Returns:
        dict[str,Any]: context that is comment across the different views
    """

    std_context_dict: dict[str, Any] = {}
    mkdoc_running: bool = False
    docs_available: bool = False
    # mkdocs

    mkdocs = MkdocsControl()
    mkdoc_running = mkdocs.is_process_running()

    em = ENVManipulator(settings.ENV_LOCATION)
    setup_step = em.read("setup_step")

    if setup_step == "2" or setup_step == "3":
        docs_available = True

    std_context_dict = {
        "START_AFRESH": settings.START_AFRESH,
        "mkdoc_running": mkdoc_running,
        "docs_available": docs_available,
    }

    return std_context_dict


def start_afresh(request: HttpRequest) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user

    Returns:
        HttpResponse: for loading the correct webpage
    """

    env_m: ENVManipulator
    mkdocs: MkdocsControl
    # root, dirs, files, d

    if not request.method == "GET":
        return render(request, "405.html", std_context(), status=405)

    if settings.START_AFRESH or settings.TESTING:
        for root, dirs, files in os.walk(settings.MKDOCS_DOCS_LOCATION):
            for f in files:
                os.unlink(os.path.join(root, f))
            for d in dirs:
                shutil.rmtree(os.path.join(root, d))

        env_m = ENVManipulator(settings.ENV_LOCATION)
        env_m.delete_all()

        mkdocs = MkdocsControl()
        if not mkdocs.stop(wait=True):
            return render(request, "500.html", status=500)
    return redirect("/")


def custom_404(request: HttpRequest, exception) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user
    Returns:
        HttpResponse: for loading the correct webpage
    """

    return render(request, "404.html", context=std_context(), status=404)


def custom_405(request: HttpRequest, exception) -> HttpResponse:
    """Title

    Description

    Args:
        request (HttpRequest): request from user
    Returns:
        HttpResponse: for loading the correct webpage
    """

    return render(request, "405.html", context=std_context(), status=405)
