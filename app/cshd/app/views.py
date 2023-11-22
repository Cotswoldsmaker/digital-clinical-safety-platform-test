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

sys.path.append(c.FUNCTIONS_APP)
from env_manipulation import ENVManipulator
from mkdocs_control import MkdocsControl
from docs_builder import Builder


START_AFRESH = True
if not settings.DEBUG:
    START_AFRESH = False

from .forms import (
    InstallationForm,
    TemplateSelectForm,
    PlaceholdersForm,
    MDEditForm,
    MDFileSelect,
)


def index(request: HttpRequest) -> HttpResponse:
    context: dict[str, Any] = {}
    placeholders: dict[str, str] = {}
    env_variables: dict = {}
    setup_step: str | None = None
    template_choice: str = ""
    # form

    if not (request.method == "POST" or request.method == "GET"):
        return render(request, "405.html", std_context())

    # 'environ.get' does not handle a change of envs very well, so used
    # 'env_variables = dotenv_values(find_dotenv())' instead
    env_variables = dotenv_values(find_dotenv())
    setup_step = env_variables.get("setup_step")

    if not setup_step:
        if request.method == "GET":
            context = {"form": InstallationForm()}

            return render(
                request, "installation_method.html", context | std_context()
            )

        elif request.method == "POST":
            form = InstallationForm(request.POST)
            if form.is_valid():
                env_m = ENVManipulator()
                env_m.add("setup_step", "1")
                env_m.add(
                    "GITHUB_USERNAME", form.cleaned_data["github_username_SA"]
                )
                env_m.add("GITHUB_TOKEN", form.cleaned_data["github_token_SA"])

                messages.success(
                    request, "Initialisation selections stored [tbc]"
                )

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
            form = TemplateSelectForm(request.POST)
            if form.is_valid():
                env_m = ENVManipulator()
                env_m.add("setup_step", "2")
                template_choice = form.cleaned_data["template_choice"]

                shutil.copytree(
                    f"{ c.MKDOCS }/templates/{ template_choice }",
                    c.MKDOCS_DOCS,
                    dirs_exist_ok=True,
                )

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

    elif setup_step == "2":
        if request.method == "GET":
            context = {"form": PlaceholdersForm()}

            return render(
                request, "placeholders_show.html", context | std_context()
            )

        elif request.method == "POST":
            form = PlaceholdersForm(request.POST)
            if form.is_valid():
                doc_build = Builder()
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
    return render(request, "500.html", std_context())


def edit_md(request: HttpRequest) -> HttpResponse:
    context: dict[str, Any] = {}
    files_md: str = ""
    loop_exit: bool = False
    files: list[str] = []
    name: str = ""

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html")

    if request.method == "GET":
        if not os.path.isdir(c.MKDOCS_DOCS):
            return render(request, "500.html", std_context())

        # TODO: can we somehow remove p and v here?
        for p, v, files in os.walk(c.MKDOCS_DOCS):
            for name in files:
                if fnmatch(name, "*.md"):
                    files_md = name
                    loop_exit = True
                    break
            if loop_exit:
                break

    elif request.method == "POST":
        form = MDFileSelect(request.POST)
        if form.is_valid():
            files_md = form.cleaned_data["mark_down_file"]
        else:
            context = {"form": form}
            return render(request, "edit_md.html", context | std_context())

    with open(f"{ c.MKDOCS_DOCS }{ files_md }", "r") as file:
        form_fields = {"text_md": file.read(), "document_name": files_md}

    context = {
        "MDFileSelect": MDFileSelect(initial={"mark_down_file": files_md}),
        "text_md": MDEditForm(initial=form_fields),
        "document_name": files_md,
    }

    return render(request, "edit_md.html", context | std_context())


def saved_md(request: HttpRequest) -> HttpResponse:
    context: dict = {}
    text_md_returned: str = ""
    file_md_returned: str = ""
    file_path: str = ""

    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "405.html")

    if request.method == "GET":
        return redirect("/edit_md")

    elif request.method == "POST":
        form = MDEditForm(request.POST)
        if form.is_valid():
            file_md_returned = form.cleaned_data["document_name"]
            text_md_returned = form.cleaned_data["text_md"]

            file_path = f"{ c.MKDOCS_DOCS }{ file_md_returned }"

            if not os.path.isfile(file_path):
                return render(request, "500.html", context | std_context())

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


def log_hazard(request: HttpRequest) -> HttpResponse:
    context: dict[str, Any] = {}
    if not (request.method == "GET" or request.method == "POST"):
        return render(request, "500.html", std_context())

    context = {}

    return render(request, "log_hazard.html", context | std_context())


def mkdoc_redirect(request: HttpRequest, path: str) -> HttpResponse:
    mkdocs: MkdocsControl

    mkdocs = MkdocsControl()
    mkdocs.start()

    if path == "home":
        return redirect(f"http://localhost:9000")
    else:
        return redirect(f"http://localhost:9000/{ path }")


# -----


def std_context() -> dict[str, Any]:
    std_context_dict: dict[str, Any] = {}
    mkdoc_running: bool = False
    # mkdocs

    mkdocs = MkdocsControl()
    mkdoc_running = mkdocs.is_process_running()

    std_context_dict = {
        "START_AFRESH": START_AFRESH,
        "mkdoc_running": mkdoc_running,
    }

    return std_context_dict


def start_afresh(request: HttpRequest) -> HttpResponse:
    env_m: ENVManipulator
    mkdocs: MkdocsControl
    # root, dirs, files, d

    if START_AFRESH:
        for root, dirs, files in os.walk(c.MKDOCS_DOCS):
            for f in files:
                os.unlink(os.path.join(root, f))
            for d in dirs:
                shutil.rmtree(os.path.join(root, d))

        env_m = ENVManipulator()
        env_m.delete("setup_step")
        env_m.delete("GITHUB_USERNAME")
        env_m.delete("GITHUB_TOKEN")

        mkdocs = MkdocsControl()
        if not mkdocs.stop(wait=True):
            return render(request, "500.html")
    return redirect("/")


def custom_404(request: HttpRequest, exception) -> HttpResponse:
    return render(request, "404.html", context=std_context(), status=404)


def custom_405(request: HttpRequest, exception) -> HttpResponse:
    return render(request, "405.html", context=std_context(), status=405)
