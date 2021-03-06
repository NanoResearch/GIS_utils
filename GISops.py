# suppress annoying pandas openpyxl warning
from __future__ import print_function

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

import time
import numpy as np
import fiona
from shapely.geometry import Point, LineString, shape, asLineString, mapping
from shapely import affinity
from shapely.ops import cascaded_union, transform
from functools import partial
import pyproj
import pandas as pd
import shutil
import GISio
try:
    from rtree import index
except:
    print('Warning: rtree not installed - some functions will not work')

def clip_raster(inraster, features, outraster):

    rasterio = import_rasterio() # check for rasterio
    from rasterio.tools.mask import mask

    geoms = _to_geojson(features)

    with rasterio.open(inraster) as src:
        print('clipping {}...'.format(inraster))
        out_image, out_transform = mask(src, geoms, crop=True)
        out_meta = src.meta.copy()

        out_meta.update({"driver": "GTiff",
                         "height": out_image.shape[1],
                         "width": out_image.shape[2],
                         "transform": out_transform})

        with rasterio.open(outraster, "w", **out_meta) as dest:
            dest.write(out_image)
            print('wrote {}'.format(outraster))

def projectdf(df, projection1, projection2):
    """Reproject a dataframe's geometry column to new coordinate system

    Parameters
    ----------
    df: dataframe
        Contains "geometry" column of shapely geometries

    projection1: string
        Proj4 string specifying source projection
    projection2: string
        Proj4 string specifying destination projection
    """
    projection1 = str(projection1)
    projection2 = str(projection2)


    # define projections
    pr1 = pyproj.Proj(projection1, errcheck=True, preserve_units=True)
    pr2 = pyproj.Proj(projection2, errcheck=True, preserve_units=True)

    # projection function
    # (see http://toblerity.org/shapely/shapely.html#module-shapely.ops)
    project = partial(pyproj.transform, pr1, pr2)

    # do the transformation!
    newgeo = [transform(project, g) for g in df.geometry]

    return newgeo

def project(geom, projection1, projection2):
    """Reproject a shapely geometry object to new coordinate system

    Parameters
    ----------
    geom: shapely geometry object
    projection1: string
        Proj4 string specifying source projection
    projection2: string
        Proj4 string specifying destination projection
    """
    projection1 = str(projection1)
    projection2 = str(projection2)


    # define projections
    pr1 = pyproj.Proj(projection1, errcheck=True, preserve_units=True)
    pr2 = pyproj.Proj(projection2, errcheck=True, preserve_units=True)

    # projection function
    # (see http://toblerity.org/shapely/shapely.html#module-shapely.ops)
    project = partial(pyproj.transform, pr1, pr2)

    # do the transformation!
    return transform(project, geom)

def project_raster(src_raster, dst_raster, dst_crs,
                   resampling=1, resolution=None, num_threads=2):
    """Reproject a raster from one coordinate system to another using Rasterio
    code from: https://github.com/mapbox/rasterio/blob/master/docs/reproject.rst

    Parameters
    ----------
    src_raster : str
        Filename of source raster.
    dst_raster : str
        Filename of reprojected (destination) raster.
    dst_crs : str
        Coordinate system of reprojected raster.
        Examples:
            'EPSG:26715'
    resampling : int (see rasterio source code: https://github.com/mapbox/rasterio/blob/master/rasterio/enums.py)
        nearest = 0
        bilinear = 1
        cubic = 2
        cubic_spline = 3
        lanczos = 4
        average = 5
        mode = 6
        gauss = 7
        max = 8
        min = 9
        med = 10
        q1 = 11
        q3 = 12
    resolution : tuple of floats (len 2)
        cell size of the output raster
        (x resolution, y resolution)
    """
    rasterio = import_rasterio() # check for rasterio
    from rasterio.warp import calculate_default_transform, reproject

    with rasterio.open(src_raster) as src:
        affine, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=resolution)
        kwargs = src.meta.copy()
        kwargs.update({
            'crs': dst_crs,
            'transform': affine,
            'affine': affine,
            'width': width,
            'height': height
        })
        with rasterio.open(dst_raster, 'w', **kwargs) as dst:
            for i in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, i),
                    destination=rasterio.band(dst, i),
                    src_transform=src.affine,
                    src_crs=src.crs,
                    dst_transform=affine,
                    dst_crs=dst_crs,
                    resampling=resampling,
                    num_threads=num_threads)

def build_rtree_index(geom):
    """Builds an rtree index. Useful for multiple intersections with same index.

    Parameters
    ==========
    geom : list
        list of shapely geometry objects
    Returns
        idx : rtree spatial index object
    """
    from rtree import index

    # build spatial index for items in geom1
    print('\nBuilding spatial index...')
    ta = time.time()
    idx = index.Index()
    for i, g in enumerate(geom):
        idx.insert(i, g.bounds)
    print("finished in {:.2f}s".format(time.time() - ta))
    return idx

def projectdf_XY(df, xcolin, ycolin, xcoltrans, ycoltrans, projection1, projection2):
    """

    :param df: dataframe containing X and Y data to transform. NB - new columns will be written in place!
    :param xcolin: column of df with X coordinate in projection1
    :param ycolin: column of df with Y cordinate in projection1
    :param xcoltrans: column of df THAT WILL BE WRITTEN with X projected to projection2
    :param ycoltrans: column of df THAT WILL BE WRITTEN with Y projected to projection2
    :param projection1: (string) Proj4 string specifying source projection
    :param projection2: (string) Proj4 string specifying destination projection
    """
    projection1 = str(projection1)
    projection2 = str(projection2)

    # define projections
    pr1 = pyproj.Proj(projection1, errcheck=True, preserve_units=True)
    pr2 = pyproj.Proj(projection2, errcheck=True, preserve_units=True)


    df[xcoltrans], df[ycoltrans] = pyproj.transform(pr1, pr2, df[xcolin].tolist(), df[ycolin].tolist())




def intersect_rtree(geom1, geom2):
    """Intersect features in geom1 with those in geom2. For each feature in geom2, return a list of
     the indices of the intersecting features in geom1.

    Parameters:
    ----------
    geom1 : list or rtree spatial index object
        list of shapely geometry objects
    geom2 : list
        list of shapely polygon objects to be intersected with features in geom1
    index :
        use an index that has already been created

    Returns:
    -------
    A list of the same length as geom2; containing for each feature in geom2,
    a list of indicies of intersecting geometries in geom1.
    """
    if isinstance(geom1, list):
        idx = build_rtree_index(geom1)
    else:
        idx = geom1
    isfr = []
    print('\nIntersecting {} features...'.format(len(geom2)))
    ta = time.time()
    for pind, poly in enumerate(geom2):
        print('\r{}'.format(pind + 1), end='')
        # test for intersection with bounding box of each polygon feature in geom2 using spatial index
        inds = [i for i in idx.intersection(poly.bounds)]
        # test each feature inside the bounding box for intersection with the polygon geometry
        inds = [i for i in inds if geom1[i].intersects(poly)]
        isfr.append(inds)
    print("\nfinished in {:.2f}s\n".format(time.time() - ta))
    return isfr

def intersect_brute_force(geom1, geom2):
    """Same as intersect_rtree, except without spatial indexing. Fine for smaller datasets,
    but scales by 10^4 with the side of the problem domain.

    Parameters:
    ----------
    geom1 : list
        list of shapely geometry objects
    geom2 : list
        list of shapely polygon objects to be intersected with features in geom1

    Returns:
    -------
    A list of the same length as geom2; containing for each feature in geom2,
    a list of indicies of intersecting geometries in geom1.
    """

    isfr = []
    ngeom1 = len(geom1)
    print('Intersecting {} features...'.format(len(geom2)))
    for i, g in enumerate(geom2):
        print('\r{}'.format(i+1), end='')
        intersects = np.array([r.intersects(g) for r in geom1])
        inds = list(np.arange(ngeom1)[intersects])
        isfr.append(inds)
    print('')
    return isfr


def dissolve(inshp, outshp, dissolve_attribute):
    df = GISio.shp2df(shp, geometry=True)
    
    df_out = dissolve_df(df, dissolve_attribute)
    
    # write dissolved polygons to new shapefile
    GISio.df2shp(df_out, outshp, 'geometry', inshp[:-4]+'.prj')


def dissolve_df(in_df, dissolve_attribute):
    
    print("dissolving DataFrame on {}".format(dissolve_attribute))
    # unique attributes on which to make the dissolve
    dissolved_items = list(np.unique(in_df[dissolve_attribute]))
    
    # go through unique attributes, combine the geometries, and populate new DataFrame
    df_out = pd.DataFrame()
    length = len(dissolved_items)
    knt = 0
    for item in dissolved_items:
        df_item = in_df[in_df[dissolve_attribute] == item]
        geometries = list(df_item.geometry)
        dissolved = cascaded_union(geometries)
        dict = {dissolve_attribute: item, 'geometry': dissolved}
        df_out = df_out.append(dict, ignore_index=True)
        knt +=1
        print('\r{:d}%'.format(100*knt/length))
        
    return df_out

def contour2shp(contours, outshape='contours.shp', 
                add_fields={},
                **kwargs):
    """Convert matplotlib contour plot object to shapefile.

    Parameters
    ----------
    contours : matplotlib.contour.QuadContourSet or list of them
        (object returned by matplotlib.pyplot.contour)
    outshape : str
        path of output shapefile
    add_fields : dict of lists or 1D arrays
        Add fields (keys=fieldnames), with attribute data (values=lists) to shapefile. 
        Attribute data must be of the same length, and in the same order as the
        total number of contour objects x number of levels in each object.
    **kwargs : key-word arguments to GISio.df2shp

    Returns
    -------
    df : dataframe of shapefile contents
    """
    from GISio import df2shp

    if not isinstance(contours, list):
        contours = [contours]

    geoms = []
    level = []
    for ctr in contours:
        levels = ctr.levels
        for i, c in enumerate(ctr.collections):
            paths = c.get_paths()
            geoms += [LineString(p.vertices) for p in paths]
            level += list(np.ones(len(paths)) * levels[i])
    
    d = {'geometry': geoms, 'level': level}
    d.update(add_fields)
    df = pd.DataFrame(d)
    df2shp(df, outshape, **kwargs)
    return df


def join_csv2shp(shapefile, shp_joinfield, csvfile, csv_joinfield, out_shapefile, how='outer'):
    '''
    add attribute information to shapefile from csv file
    shapefile: shapefile to add attributes to
    shp_joinfield: attribute name in shapefile on which to make join
    csvfile: csv file with information to be added to shapefile
    csv_joinfield: column in csv with entries matching those in shp_joinfield
    out_shapefile: output; original shapefile is not modified
    type: pandas join type; see http://pandas.pydata.org/pandas-docs/dev/generated/pandas.DataFrame.join.html
    '''

    shpdf = GISio.shp2df(shapefile, index=shp_joinfield, geometry=True)

    csvdf = pd.read_csv(csvfile, index_col=csv_joinfield)

    print('joining to {}...'.format(csvfile))
    joined = shpdf.join(csvdf, how='inner', lsuffix='L', rsuffix='R')

    # write to shapefile
    GISio.df2shp(joined, out_shapefile, 'geometry', shapefile[:-4]+'.prj')


def rotate_coords(coords, rot, origin):
    """
    Rotates a set of coordinates (wrapper for shapely)
    coords: sequence point tuples (x, y)
    """
    ur = LineString(unrotated)
    r = affinity.rotate(ur, rot, origin=ur[0])

    return list(zip(r.coords.xy[0], r.coords.xy[1]))


def import_rasterio():
    try:
        import rasterio
        from rasterio.warp import calculate_default_transform, reproject, RESAMPLING
        return rasterio
    except:
        print('This function requires rasterio.')


def _to_geojson(features):
    """convert input features to list of geojson geometries."""

    if isinstance(features, str): # features are in a shapefile
        with fiona.open(features, "r") as shp:
            geoms = [feature["geometry"] for feature in shp]
    elif isinstance(features, list):
        if isinstance(features[0], dict): # features are geo-json
            try:
                shape(features[0])
                geoms = features
            except:
                raise TypeError('Unrecognized feature type')
        else: # features are shapely geometries
            try:
                mapping(features[0])
                geoms = [mapping(f) for f in features]
            except:
                raise TypeError('Unrecognized feature type')
    return geoms