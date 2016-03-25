import json

from ytdl.models import Video, Channel, ALL_SERVICES
import ytdl.tasks

from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.http import HttpResponse, Http404
from django.template import RequestContext
from django.db.models import Q
from django.shortcuts import render_to_response, get_object_or_404, redirect
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


def index(request):
    from django.db.models import Count
    channels = Channel.objects.order_by('chanid').all().annotate(num_videos = Count('video'))
    recent = Video.objects.all().order_by('publishdate').reverse().filter(status=Video.STATE_NEW)[:5]

    # Sort channels based on lower-case ID (easier and just as
    # quick to do this in non-QuerySet manner)
    channels = sorted(channels, key = lambda c: c.chanid.lower())

    # Show "active" videos (downloading, errored, queued)
    downloads = Video.objects.filter(Q(status=Video.STATE_DOWNLOADING) | Q(status=Video.STATE_QUEUED) | Q(status=Video.STATE_GRAB_ERROR)).reverse().all()

    return render_to_response(
        'ytdl/list_channels.html',
        {"channels": channels, "recent": recent, "downloads": downloads})


def view_channel(request, chanid):
    all_videos = Video.objects.order_by('publishdate').reverse().all()
    if chanid == "_all":
        channel = None
    else:
        channel = get_object_or_404(Channel, pk=chanid)
        all_videos = all_videos.filter(channel=channel)

    query = request.GET.get('search', "")
    if len(query) > 0:
        all_videos = all_videos.filter(title__icontains=query)

    # Filtering by status
    # FIXME: Expose/retain this in webUI
    status = request.GET.get('status', "")
    if len(status) > 0:
        all_videos = all_videos.filter(status=status)

    # 25 videos per page, with no less than 5 per page
    paginator = Paginator(all_videos, per_page=25, orphans=5)


    page = request.GET.get('page')
    try:
        videos = paginator.page(page)
    except PageNotAnInteger:
        videos = paginator.page(1)
    except EmptyPage:
        videos = paginator.page(paginator.num_pages)

    return render_to_response('ytdl/view_channel.html',
                              {"channel": channel,
                               "videos": videos,
                               "query": query})


def grab(request, videoid):
    video = get_object_or_404(Video, id=videoid)

    force = request.REQUEST.get("force", "false").lower() == "true"

    grabbable = video.status in [Video.STATE_NEW, Video.STATE_GRAB_ERROR]
    if not grabbable and not force:
        return HttpResponse(
            "Bad. Already grabbed (status %s)" % (video.status),
            status=500)

    video.status = Video.STATE_QUEUED
    video.save()
    ytdl.tasks.grab_video.delay(video.id, force=force)
    return HttpResponse("ok" + " (force)"*(int(force)))


def _set_status(videoid, status):
    video = get_object_or_404(Video, id=videoid)
    video.status = status
    video.save()
    return HttpResponse(json.dumps({"status": video.status}))


def mark_viewed(request, videoid):
    return _set_status(videoid, Video.STATE_GRABBED)


def mark_ignored(request, videoid):
    return _set_status(videoid, status=Video.STATE_IGNORE)


def refresh_all(request):
    channels = Channel.objects.all()
    for c in channels:
        ytdl.tasks.refresh_channel.delay(id=c.id)

    return HttpResponse("ok")


def refresh_channel(request, chanid):
    channel = get_object_or_404(Channel, id=chanid)
    ytdl.tasks.refresh_channel.delay(id=channel.id)

    return HttpResponse("ok")

from django.views.decorators.csrf import csrf_protect
@csrf_protect
def add_channel(request):
    if request.method == "GET":
        return render_to_response("ytdl/add_channel.html", {},
                                  context_instance=RequestContext(request))
    else:
        # Get data form form
        channame = request.POST['channame']
        service = request.POST['service']

        # Check service is valid
        if service not in ALL_SERVICES:
            return HttpResponse(
                "Invalid service selected, should be in %r" % (ALL_SERVICES),
                status=500)

        # TODO: Verify channel exists, give useful error

        # Check if channel exists already added
        try:
            c = Channel.objects.get(chanid=request.POST['channame'])
        except Channel.DoesNotExist:
            pass
        else:
            return redirect(c)

        # Create new channel
        channel = Channel(chanid=channame, service=service)
        channel.save()

        # Trigger initial update
        ytdl.tasks.refresh_channel.delay(id=channel.id)

        # View newly added channel
        return redirect(channel)


@csrf_protect
def channel_delete(request):
    if request.method == "GET":
        channels = Channel.objects.all()
        return render_to_response("ytdl/delete_channel.html", {'channels': channels},
                                  context_instance=RequestContext(request))
    else:
        pk = request.POST['pk']
        c = get_object_or_404(Channel, pk=pk)

        # Delete channel and videos
        c.delete()
        return redirect(index)