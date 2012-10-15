from ytdl.models import Video, Channel
import ytdl.tasks

from django.http import HttpResponse
from django.shortcuts import render_to_response, get_object_or_404
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger


def index(request):
    channels = Channel.objects.all()
    return render_to_response('ytdl/index.html', {"channels": channels})


def view_channel(request, chanid):
    channel = get_object_or_404(Channel, chanid=chanid)

    all_videos = Video.objects.order_by('publishdate').reverse().all()
    all_videos = all_videos.filter(channel=channel)

    query = request.GET.get('search', "")
    if len(query) > 0:
        all_videos = all_videos.filter(title__icontains=query)

    paginator = Paginator(all_videos, 25)

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


def mark_viewed(request, videoid):
    video = get_object_or_404(Video, id=videoid)
    video.status = Video.STATE_GRABBED
    video.save()

    return HttpResponse("ok")


def refresh_channel(request, chanid):
    channel = get_object_or_404(Channel, id=chanid)
    ytdl.tasks.refresh_channel.delay(id=channel.id)

    return HttpResponse("ok")


def add_channel(request, chanid):
    try:
        channel = Channel.objects.get(chanid=chanid)
    except Channel.DoesNotExist:
        pass
    else:
        return HttpResponse("exists", status=500)

    channel = Channel(chanid=chanid)
    channel.save()
    ytdl.tasks.refresh_channel.delay(id=channel.id)
    return HttpResponse("ok")
